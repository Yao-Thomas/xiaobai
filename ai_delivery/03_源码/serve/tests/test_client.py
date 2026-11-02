# -*- coding: utf-8 -*-
"""test_client.py —— 客户端（超时/重试/降级标志）的单元测试（无 fastapi 依赖）。"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_SERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVE not in sys.path:
    sys.path.insert(0, _SERVE)

import client  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.startswith("/infer"):
            n = int(self.headers.get("Content-Length") or 0)
            _ = self.rfile.read(n) if n else b""
            resp = {"ok": True, "label": "square", "confidence": 0.9,
                    "detail": {}, "elapsed_ms": 3}
            data = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class TestClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_infer_ok(self):
        c = client.InferClient("http://127.0.0.1:%d" % self.port, timeout=2.0)
        r = c.infer("waveform", [0] * 4096)
        self.assertTrue(r["ok"])
        self.assertEqual(r["label"], "square")

    def test_timeout_offline_flag(self):
        # 指向不可达端口(9) + 极短超时 -> 返回 ok:false 且带 offline 降级标志
        c = client.InferClient("http://127.0.0.1:9", timeout=0.2, retries=0)
        r = c.infer("waveform", [0] * 4096)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("offline"))

    def test_infer_raw(self):
        c = client.InferClient("http://127.0.0.1:%d" % self.port, timeout=2.0)
        r = c.infer_raw({"type": "waveform", "data": [0] * 4096})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()
