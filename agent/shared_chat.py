#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shared_chat.py —— 共享对话记录（板载 UI 和 PC 客户端看同一份）

════════════════════════════════════════════════════════════════════
要解决什么问题（用户报的）
════════════════════════════════════════════════════════════════════
用户："对话和板子不一致，没同步啊"

诊断下来，板子上原本有【三套】互不相通的会话存储：

    ① 板载 UI（ui/apps_agent.py）
         /home/zynq/.agent_chats.json     ← 板子屏幕上聊天用的
         格式：{"cur": 2, "sessions": [{"title":..., "msgs":[[who,text],...]}]}

    ② agent/sessions.py 的 Store
         /var/lib/xiaobai/sessions/       ← ★ 一直是空的
         格式：每个会话一个 <id>.json

    ③ PC 客户端（xb_chat.py）
         ~/.xiaobai_chat_sessions/        ← 自己一套，从不和板子往来

  而 PC 端和板载 UI 调的其实是【同一个】agent 接口（POST /voice），
  只是各自记各自的账 ⇒ 永远对不上。

════════════════════════════════════════════════════════════════════
这一层的做法
════════════════════════════════════════════════════════════════════
★ 把"记会话"下沉到 agent 层，并且【复用板载 UI 的那个文件】——
  因为那个文件已经有内容（板子上聊过的历史），而且板载 UI 启动时会读它。

     agent 收到 /voice
         └─→ 问答追加进 .agent_chats.json（本模块）
                    │
     ┌──────────────┴──────────────┐
     │                             │
  板载 UI 下次启动 load_sessions    cloud_api /chat/sessions
  就读到了（PC 发的话也看得到）      PC 客户端从这里拉

════════════════════════════════════════════════════════════════════
两个必须处理的坑
════════════════════════════════════════════════════════════════════
① 并发写：板载 UI 和 agent 都可能写同一个文件。
   ⇒ 用文件锁（fcntl.flock）+ 读-改-写 + 原子替换。
     板载 UI 那边没加锁，但它的写很稀疏（一问一写），
     加上我们用同样的"临时文件 + os.replace"，至少不会写坏。

② 重复记：板载 UI 问完自己也 save_sessions()。
   ⇒ /voice 支持一个 "source" 参数：
        source="ui"  -> 板载 UI 自己会记，agent 【不再重复记】
        其它/不传    -> agent 负责记（PC 端走这条）
     这样两边都不重复、也都不会漏。
════════════════════════════════════════════════════════════════════
"""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★ 和板载 UI（ui/apps_agent.py 的 SESS_FILE）指向同一个文件 —— 这是关键
CHAT_FILE = os.environ.get("AGENT_CHATS", "/home/zynq/.agent_chats.json")

# 容量上限：板子只有 1GB 内存 + 有限 flash，不能无限涨
MAX_SESSIONS = 40
MAX_MSGS = 60

_LOCK_FILE = CHAT_FILE + ".lock"


class _Lock(object):
    """文件锁（拿不到锁也不阻塞太久，宁可少记一条也别卡住对话）"""

    def __init__(self, path=_LOCK_FILE, timeout=3.0):
        self.path = path
        self.timeout = timeout
        self.fh = None

    def __enter__(self):
        try:
            import fcntl
            self.fh = open(self.path, "a+")
            t0 = time.time()
            while True:
                try:
                    fcntl.flock(self.fh.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except Exception:
                    if time.time() - t0 > self.timeout:
                        return self          # 超时就放弃加锁，继续做
                    time.sleep(0.05)
        except Exception:
            return self

    def __exit__(self, *a):
        try:
            if self.fh:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
                self.fh.close()
        except Exception:
            pass
        return False


def _read():
    """读整个文件（容错：坏了就当空的，别让对话崩掉）"""
    try:
        with open(CHAT_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {"cur": 0, "sessions": []}
        if not isinstance(d.get("sessions"), list):
            d["sessions"] = []
        return d
    except Exception:
        return {"cur": 0, "sessions": []}


def _write(d):
    """原子写（临时文件 + replace，避免断电/并发留下半个文件）"""
    try:
        os.makedirs(os.path.dirname(CHAT_FILE) or ".", exist_ok=True)
        tmp = CHAT_FILE + ".tmp.agent"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, CHAT_FILE)
        try:
            os.chmod(CHAT_FILE, 0o644)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _new_sid():
    """生成会话 id（稳定引用 —— 不然归档/删除会让下标错位）"""
    return "s%d_%04d" % (int(time.time()), int(time.time() * 10000) % 10000)


def ensure_ids(d):
    """给没有 id 的会话补一个（向后兼容老数据）

    ★★★ 为什么需要 id（2026-10-03）：
      原来板载 UI 用【数组下标】引用会话，PC 端用 "board_<下标>"。
      一旦删除或归档，后面的会话下标就全变了 ⇒ PC 端点"第 3 个"
      会打开完全不同的会话。
      ⇒ 给每个会话一个稳定 id，两边都用 id 说话。
    """
    changed = False
    for i, s in enumerate(d.get("sessions") or []):
        if isinstance(s, dict) and not s.get("id"):
            s["id"] = "s%03d_%s" % (i, abs(hash(str(s.get("title")))) % 10000)
            changed = True
    return changed


def archive(session_id, on=True):
    """归档 / 取消归档一个会话（两边同步）"""
    with _Lock():
        d = _read()
        ensure_ids(d)
        hit = None
        for s in (d.get("sessions") or []):
            if isinstance(s, dict) and str(s.get("id")) == str(session_id):
                s["archived"] = bool(on)
                hit = s
                break
        if hit is None:
            # 兼容：也可能是 board_N 形式
            sid = str(session_id or "")
            if sid.startswith("board_"):
                try:
                    i = int(sid[6:])
                    ss = d.get("sessions") or []
                    if 0 <= i < len(ss):
                        ss[i]["archived"] = bool(on)
                        hit = ss[i]
                except Exception:
                    pass
        if hit is not None:
            _write(d)
            return True, hit.get("title")
    return False, None


def append(user_text, reply_text, source="pc", title=None):
    """把一轮问答记进【外部消息区】而不是直接改 sessions

    ★★★ 为什么用独立的 external 字段（2026-10-03 重构）★★★
    之前的做法是直接把这一轮追加到 sessions[cur].msgs 里，
    板载 UI 那边再用"最长公共前缀"合并 —— 结果是【无限重复】：

        板载 UI 一次"你好"产生 4 条：user你好 + sys×2 + bot回复
        agent   记的是      2 条：user你好 + bot回复
        前缀只匹配第 1 条 ⇒ 走"两边都有新增"分支
            结果 = disk(2) + mem[1:](3) = 5 条
        下一轮 disk(2) + mem[1:](4) = 6 条 …每合并一次涨一条

    根因：两边记的【序列本来就不一样】（板载 UI 含工具调用记录），
          用前缀对齐必然错位。

    ⇒ 改成：agent 只往 external 里追加，板载 UI 的 sessions 【完全不动】。
      板载 UI 读的时候把没见过的 external 条目追加到当前会话显示，
      但不写回 sessions ⇒ 两边永不冲突、也不会重复。

    格式：
        {"cur":…, "sessions":[…],
         "external":[{"s":2, "u":"用户说的", "b":"小白答的",
                      "t":1791018471.5, "seen":false}, …]}
      s    = 归属的会话序号（记的时候的 cur）
      seen = 板载 UI 是否已经显示过（显示过就不再重复追加）
    """
    if source == "ui":
        return None
    user_text = (str(user_text or "")).strip()
    reply_text = (str(reply_text or "")).strip()
    if not user_text:
        return None

    with _Lock():
        d = _read()
        cur = int(d.get("cur") or 0)
        ext = d.get("external")
        if not isinstance(ext, list):
            ext = []
        ext.append({"s": cur, "u": user_text, "b": reply_text,
                    "t": time.time(), "seen": False})
        # 上限：external 也别无限涨（板子内存有限）
        if len(ext) > 200:
            del ext[:-200]
        d["external"] = ext
        _write(d)
        return (title or user_text)[:18]


def _ext_of(d, idx):
    """取 external 里属于会话 idx 的条目"""
    out = []
    for e in (d.get("external") or []):
        if not isinstance(e, dict):
            continue
        try:
            if int(e.get("s") or 0) == idx:
                out.append(e)
        except Exception:
            continue
    return out


def list_sessions(limit=MAX_SESSIONS, include_archived=False):
    """列出会话（给 /chat/sessions 用）

    ★ external（PC 端通过 agent 发的）也算进 msg_count，
      不然 PC 端看到的条数会比实际少。
    ★ 默认【不列已归档的】（用户要的"归档隐藏"）；
      include_archived=True 时列出来并带 archived 标记。
    """
    d = _read()
    if ensure_ids(d):
        try:
            _write(d)
        except Exception:
            pass
    ss = d.get("sessions") or []
    out = []
    for i, s in enumerate(ss):
        if not isinstance(s, dict):
            continue
        if s.get("archived") and not include_archived:
            continue
        msgs = s.get("msgs") or []
        mine = _ext_of(d, i)
        last = ""
        if mine:
            last = str(mine[-1].get("b") or mine[-1].get("u") or "")[:60]
        if not last and msgs and len(msgs[-1]) >= 2:
            last = str(msgs[-1][1])[:60]
        out.append({
            "id": str(s.get("id") or ("board_%d" % i)),
            "idx": i,                                  # 内部用，兼容老调用
            "title": s.get("title") or "新对话",
            "msg_count": len(msgs) + len(mine) * 2,   # 外部一问一答算 2 条
            "cur": (i == int(d.get("cur") or 0)),
            "archived": bool(s.get("archived")),
            "source": "board-ui",
            "updated": 0,
            "last": last,
        })
    return out[-limit:]


def _resolve_idx(d, session_id):
    """把 id（或老的 board_N）解析成数组下标"""
    sid = str(session_id or "")
    ss = d.get("sessions") or []
    # ① 先按 id 找（现在的主路径）
    for i, s in enumerate(ss):
        if isinstance(s, dict) and str(s.get("id")) == sid:
            return i
    # ② 兼容老的 board_N
    if sid.startswith("board_"):
        try:
            i = int(sid[6:])
            if 0 <= i < len(ss):
                return i
        except Exception:
            pass
    # ③ 只有一个会话时，随便给（客户端有时只传空）
    if len(ss) == 1:
        return 0
    return None


def history(session_id):
    """拿某个会话的消息（给 /chat/history 用）

    ★ 合并两处：板载 UI 自己的 msgs + external 里归属本会话的问答
      （external 是 PC 端通过 agent 发的，独立存放，不会和板载 UI 打架）
    """
    d = _read()
    idx = _resolve_idx(d, session_id)
    if idx is None:
        return []
    ss = d.get("sessions") or []
    if idx < 0 or idx >= len(ss):
        return []
    s = ss[idx]
    if not isinstance(s, dict):
        return []
    out = []
    for m in (s.get("msgs") or []):
        if isinstance(m, (list, tuple)) and len(m) >= 2:
            who = "user" if str(m[0]) == "user" else "assistant"
            out.append({"role": who, "content": str(m[1])})
    for e in _ext_of(d, idx):
        if e.get("u"):
            out.append({"role": "user", "content": str(e["u"])})
        if e.get("b"):
            out.append({"role": "assistant", "content": str(e["b"])})
    return out


def stats():
    d = _read()
    ss = d.get("sessions") or []
    try:
        size = os.path.getsize(CHAT_FILE)
    except Exception:
        size = 0
    return {"sessions": len(ss), "max_sessions": MAX_SESSIONS,
            "max_msgs": MAX_MSGS, "bytes": size, "file": CHAT_FILE,
            "source": "board-ui 共享文件"}


# ══════════════════════════════════════════════════════════════════
#  ★★★ SharedStore —— 和 agent/sessions.py 的 Store 接口一致
# ══════════════════════════════════════════════════════════════════
# 为什么要这个适配器：
#   cloud_api.py 的 _sessions() 原来返回 agent.sessions.Store，
#   而那个 Store 读写的是 /var/lib/xiaobai/sessions/（永远是空的），
#   和板载 UI 的 .agent_chats.json 完全两回事 ⇒ 客户端看不到板子的对话。
#
#   ⇒ 让 _sessions() 返回这个适配器：接口和 Store 一模一样，
#     数据却落在板载 UI 那个共享文件里。
#     cloud_api 那边【一行都不用改】。
# ══════════════════════════════════════════════════════════════════
class SharedStore(object):
    """Store 的替身：读写板载 UI 的共享会话文件"""

    def __init__(self, verbose=False):
        self.verbose = verbose

    # ---- 读 ----
    def load(self, sid):
        d = _read()
        i = self._idx(sid, d)
        return (d.get("sessions") or [])[i] if i is not None else None

    def _idx(self, sid, d=None):
        d = d or _read()
        ss = d.get("sessions") or []
        # ★ 先按稳定 id 找（归档/删除后下标会变，必须用 id）
        r = _resolve_idx(d, sid)
        if r is not None:
            return r
        # 没带 id 就按当前会话算（客户端常常只传空）
        c = int(d.get("cur") or 0)
        return c if 0 <= c < len(ss) else None

    def history(self, sid, limit=None):
        """★ 直接复用模块级 history() —— 它会把 external 的问答也合进来"""
        d = _read()
        i = self._idx(sid, d)
        if i is None:
            return []
        h = history("board_%d" % i)
        return h[-limit:] if limit else h

    def turns(self, sid):
        return len([m for m in self.history(sid) if m["role"] == "user"])

    def list(self, limit=MAX_SESSIONS):
        return list_sessions(limit)

    def stats(self):
        return stats()

    def export(self, sid, fmt="md"):
        d = _read()
        i = self._idx(sid, d)
        if i is None:
            return None
        s = (d.get("sessions") or [])[i]
        lines = ["# %s" % (s.get("title") or "对话"), ""]
        for m in (s.get("msgs") or []):
            if isinstance(m, (list, tuple)) and len(m) >= 2:
                who = "**用户**" if str(m[0]) == "user" else "**小白**"
                lines.append("%s：%s" % (who, m[1]))
                lines.append("")
        return "\n".join(lines)

    # ---- 写 ----
    def new(self, first_text="", sid=None):
        with _Lock():
            d = _read()
            ss = d.get("sessions") or []
            ss.append({"title": (str(first_text or "新对话"))[:18] or "新对话",
                       "msgs": []})
            d["sessions"] = ss[-MAX_SESSIONS:]
            d["cur"] = len(d["sessions"]) - 1
            _write(d)
        return "board_%d" % (len(d["sessions"]) - 1)

    def append(self, sid, role, content, tool_calls=None, name=None):
        """★ 写进 external，不碰板载 UI 的 sessions

        为什么：板载 UI 的 msgs 里混着 sys（工具调用记录），
        外部直接往里塞会打乱它的序列；而且它 save 时会整体重写。
        ⇒ 外部消息一律走 external，板载 UI 读的时候再合并显示。

        user / assistant 是【分两次】调的，所以这里维护一条"待配对"的：
          user 来了 -> 追加 {"u":…, "b":""}
          assistant 来了 -> 补到最近一条 b 为空的记录上
        """
        with _Lock():
            d = _read()
            ext = d.get("external")
            if not isinstance(ext, list):
                ext = []
            cur = int(d.get("cur") or 0)
            is_user = str(role) in ("user", "human")
            if is_user:
                ext.append({"s": cur, "u": str(content or ""), "b": "",
                            "t": time.time(), "seen": False})
            else:
                # 找最近一条还没配对的 user
                done = False
                for e in reversed(ext):
                    if isinstance(e, dict) and not e.get("b"):
                        e["b"] = str(content or "")
                        done = True
                        break
                if not done:
                    ext.append({"s": cur, "u": "", "b": str(content or ""),
                                "t": time.time(), "seen": False})
            if len(ext) > 200:
                del ext[:-200]
            d["external"] = ext
            _write(d)
        return True

    def delete(self, sid):
        with _Lock():
            d = _read()
            i = self._idx(sid, d)
            if i is None:
                return False
            del (d.get("sessions") or [])[i]
            d["cur"] = max(0, min(int(d.get("cur") or 0),
                                  len(d.get("sessions") or []) - 1))
            _write(d)
        return True

    def clear_all(self):
        with _Lock():
            _write({"cur": 0, "sessions": []})
        return True

    def rename(self, sid, title):
        with _Lock():
            d = _read()
            i = self._idx(sid, d)
            if i is None:
                return False
            (d.get("sessions") or [])[i]["title"] = str(title)[:40]
            _write(d)
        return True


if __name__ == "__main__":
    print("文件:", CHAT_FILE)
    print("统计:", json.dumps(stats(), ensure_ascii=False))
    for s in list_sessions():
        print("  %-6s %-20s %d 条  %s"
              % (s["id"], s["title"][:18], s["msg_count"],
                 "← 当前" if s["cur"] else ""))
