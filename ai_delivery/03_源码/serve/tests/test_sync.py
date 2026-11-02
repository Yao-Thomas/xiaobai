# -*- coding: utf-8 -*-
"""test_sync.py —— 任务 H 云端同步存储（增量同步 + 时间戳 + 以 PC 为准）单测。"""
import os
import sys
import tempfile
import unittest

_SERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVE not in sys.path:
    sys.path.insert(0, _SERVE)

import sync_store  # noqa: E402


def _rec(rid, ts, payload):
    return {"record_id": rid, "ts": ts, "payload": payload}


class TestSyncStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = sync_store.SyncStore(os.path.join(self.tmp.name, "sync.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_push_and_pull_incremental(self):
        self.store.push("pc", [_rec("a", 1.0, {"x": 1})])
        self.store.push("board", [_rec("b", 2.0, {"x": 2})])
        r = self.store.pull("board", since_seq=0)
        self.assertTrue(r["ok"])
        self.assertEqual([x["record_id"] for x in r["records"]], ["a", "b"])
        # 增量：只取 seq>1
        r2 = self.store.pull("board", since_seq=1)
        self.assertEqual([x["record_id"] for x in r2["records"]], ["b"])

    def test_pc_wins_conflict(self):
        self.store.push("pc", [_rec("a", 1.0, {"v": "pc"})])
        r = self.store.push("board", [_rec("a", 2.0, {"v": "board"})])
        self.assertEqual(r["rejected"][0]["record_id"], "a")
        rows = self.store.pull("pc", 0)["records"]
        self.assertEqual(rows[0]["payload"]["v"], "pc")
        self.assertEqual(rows[0]["origin"], "pc")

    def test_board_can_update_own_record(self):
        self.store.push("board", [_rec("a", 1.0, {"v": 1})])
        r = self.store.push("board", [_rec("a", 2.0, {"v": 2})])
        self.assertEqual(r["accepted"], ["a"])
        rows = self.store.pull("board", 0)["records"]
        self.assertEqual(rows[0]["payload"]["v"], 2)

    def test_pc_overwrites_board(self):
        self.store.push("board", [_rec("a", 1.0, {"v": "board"})])
        self.store.push("pc", [_rec("a", 2.0, {"v": "pc"})])
        rows = self.store.pull("pc", 0)["records"]
        self.assertEqual(rows[0]["origin"], "pc")
        self.assertEqual(rows[0]["payload"]["v"], "pc")

    def test_pull_recent_board_cache(self):
        for i in range(10):
            self.store.push("pc", [_rec("r%d" % i, float(i), {"i": i})])
        r = self.store.pull_recent("board", 3)
        self.assertEqual([x["record_id"] for x in r["records"]], ["r7", "r8", "r9"])

    def test_invalid_client_rejected(self):
        r = self.store.push("evil", [_rec("a", 1.0, {})])
        self.assertFalse(r["ok"])

    def test_malformed_record_does_not_crash_batch(self):
        r = self.store.push("pc", [_rec("a", 1.0, {"v": 1}), {"bad": True}])
        self.assertTrue(r["ok"])
        self.assertEqual(r["accepted"], ["a"])
        self.assertEqual(len(r["rejected"]), 1)

    def test_pc_available_while_board_offline(self):
        # 板子不 push（离线），PC 仍可正常 push/pull
        self.store.push("pc", [_rec("a", 1.0, {"v": 1})])
        r = self.store.pull("pc", 0)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["records"]), 1)


if __name__ == "__main__":
    unittest.main()
