# -*- coding: utf-8 -*-
"""
sync_store.py —— 任务 H：云端侧同步存储（增量同步 + 时间戳 + 以 PC 为准的冲突处理）

约定（来自 06_分工总表_核对版.md 第②节第8项，接口已冻结）：
    · 记录以 PC 端为主：PC 的写入始终生效（覆盖一切）
    · 板子存最近 N 条：板子本地只缓存最近 N 条（pull 支持 limit / pull_recent）
    · 增量同步：用服务端单调递增序号 server_seq 做游标，客户端记住上次游标即可
    · 时间戳：每条记录带 client_ts（客户端产生时间），服务端另记 updated_at
    · 冲突以 PC 为准：同一 record_id 若已存在且权威作者是 pc，板子侧 push 被拒绝
    · 板子离线时 PC 端仍可用：存储完全在云端，PC 的 push/pull 不依赖板子在线

纯标准库 sqlite3，无第三方依赖，可在无 fastapi 的机器上单测。
"""
import json
import os
import sqlite3
import threading
import time

VALID_CLIENTS = ("pc", "board")


class SyncStore:
    """云端同步存储（单进程内线程安全）。"""

    def __init__(self, db_path):
        self.db_path = db_path
        d = os.path.dirname(db_path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------ schema
    def _init_schema(self):
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_id  TEXT PRIMARY KEY,
                    origin     TEXT NOT NULL,   -- 权威作者：pc / board
                    client_id  TEXT NOT NULL,   -- 最近一次提交者
                    client_ts  REAL NOT NULL,   -- 客户端产生时间戳
                    payload    TEXT NOT NULL,   -- JSON 文本
                    server_seq INTEGER NOT NULL,-- 服务端单调递增游标（增量同步基准）
                    updated_at REAL NOT NULL    -- 服务端接收时间
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_seq ON records(server_seq)"
            )

    # ------------------------------------------------------------------ push
    def push(self, client_id, records):
        """客户端把一批记录推上来（增量合并）。

        records: list of {"record_id": str, "ts": float, "payload": any}
        返回 {"ok": True, "accepted": [rid...], "rejected": [{record_id, reason}...],
              "server_seq": int}
        """
        if client_id not in VALID_CLIENTS:
            return {"ok": False, "error": "client_id 必须是 %s" % " / ".join(VALID_CLIENTS)}
        if not isinstance(records, (list, tuple)):
            return {"ok": False, "error": "records 必须是列表"}

        accepted, rejected = [], []
        with self._lock, self._conn:
            cur = self._conn.execute("SELECT COALESCE(MAX(server_seq),0) FROM records")
            seq = int(cur.fetchone()[0])
            for r in records:
                try:
                    rid = str(r["record_id"])
                    cts = float(r.get("ts", time.time()))
                    payload = json.dumps(r.get("payload"), ensure_ascii=False)
                except Exception as e:  # noqa: BLE001 —— 单条坏记录不拖垮整批
                    rejected.append({"record_id": r.get("record_id"),
                                     "reason": "记录格式非法: %s" % e})
                    continue

                # ★ 冲突处理：以 PC 为准
                existing = self._conn.execute(
                    "SELECT origin FROM records WHERE record_id=?", (rid,)
                ).fetchone()
                if (existing is not None and existing["origin"] == "pc"
                        and client_id == "board"):
                    rejected.append({
                        "record_id": rid,
                        "reason": "conflict: PC 端记录优先，板子写入被拒绝（以 PC 为准）",
                    })
                    continue

                seq += 1
                now = time.time()
                self._conn.execute(
                    """
                    INSERT INTO records(record_id, origin, client_id, client_ts,
                                        payload, server_seq, updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(record_id) DO UPDATE SET
                        origin=excluded.origin,
                        client_id=excluded.client_id,
                        client_ts=excluded.client_ts,
                        payload=excluded.payload,
                        server_seq=excluded.server_seq,
                        updated_at=excluded.updated_at
                    """,
                    (rid, client_id, client_id, cts, payload, seq, now),
                )
                accepted.append(rid)
            self._conn.commit()

        return {"ok": True, "accepted": accepted, "rejected": rejected,
                "server_seq": int(seq)}

    # ------------------------------------------------------------------ pull
    def pull(self, client_id, since_seq=0, limit=None):
        """增量拉取：server_seq > since_seq 的记录，按 seq 升序，最多 limit 条。

        返回 {"ok": True, "records": [...], "server_seq": 最后一条的 seq}
        （调用方把 server_seq 记为下次 since_seq 即可实现增量同步。）
        """
        if client_id not in VALID_CLIENTS:
            return {"ok": False, "error": "client_id 必须是 %s" % " / ".join(VALID_CLIENTS)}
        with self._lock:
            q = "SELECT * FROM records WHERE server_seq > ? ORDER BY server_seq ASC"
            args = [int(since_seq)]
            if limit is not None:
                q += " LIMIT ?"
                args.append(int(limit))
            rows = self._conn.execute(q, args).fetchall()

        records = [self._row_to_dict(r) for r in rows]
        max_seq = records[-1]["server_seq"] if records else int(since_seq)
        return {"ok": True, "records": records, "server_seq": int(max_seq)}

    def pull_recent(self, client_id, n):
        """板子本地缓存用：最近 n 条（按 seq 降序取 n，再升序返回，便于展示）。"""
        if client_id not in VALID_CLIENTS:
            return {"ok": False, "error": "client_id 必须是 %s" % " / ".join(VALID_CLIENTS)}
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM records ORDER BY server_seq DESC LIMIT ?", (int(n),)
            ).fetchall()
        records = [self._row_to_dict(r) for r in rows][::-1]
        return {"ok": True, "records": records, "n": len(records)}

    # ------------------------------------------------------------------ 工具
    def _row_to_dict(self, r):
        return {
            "record_id": r["record_id"],
            "origin": r["origin"],
            "client_id": r["client_id"],
            "client_ts": r["client_ts"],
            "payload": json.loads(r["payload"]),
            "server_seq": r["server_seq"],
            "updated_at": r["updated_at"],
        }

    def count(self):
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def snapshot(self):
        """全部记录（诊断/演示用），按 seq 升序。"""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM records ORDER BY server_seq ASC").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def close(self):
        with self._lock:
            self._conn.close()
