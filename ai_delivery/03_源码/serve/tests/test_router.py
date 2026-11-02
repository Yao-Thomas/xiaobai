# -*- coding: utf-8 -*-
"""test_router.py —— 分级推理核心逻辑 router.route 的单元测试（无 fastapi 依赖）。"""
import os
import sys
import unittest

_SERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVE not in sys.path:
    sys.path.insert(0, _SERVE)

import router  # noqa: E402


def make_local(conf, label="square"):
    def f(req):
        return {"ok": True, "label": label, "confidence": conf,
                "detail": {"model_source": "test_local"}}
    return f


def make_cloud(ok=True, label="square", conf=0.93, error=None):
    def f(req):
        if ok:
            return {"ok": True, "label": label, "confidence": conf,
                    "detail": {"model_source": "test_cloud"}, "elapsed_ms": 5}
        return {"ok": False, "error": error or "cloud down"}
    return f


class TestRoute(unittest.TestCase):
    def test_local_confident_stays_local(self):
        calls = []

        def cloud(req):
            calls.append(1)
            raise AssertionError("本地已足够置信，不应调用云端")

        r = router.route({"type": "waveform"}, make_local(0.9), cloud, threshold=0.7)
        self.assertTrue(r["ok"])
        self.assertEqual(r["detail"]["decision_path"], "local")
        self.assertFalse(r["offline_mode"])
        self.assertEqual(calls, [])

    def test_local_low_confidence_goes_cloud(self):
        r = router.route({"type": "waveform"}, make_local(0.5), make_cloud(),
                         threshold=0.7)
        self.assertTrue(r["ok"])
        self.assertEqual(r["detail"]["decision_path"], "cloud")
        self.assertEqual(r["label"], "square")
        self.assertFalse(r["offline_mode"])

    def test_cloud_fail_fallback_local_offline(self):
        r = router.route({"type": "waveform"}, make_local(0.5),
                         make_cloud(ok=False, error="timeout"), threshold=0.7)
        self.assertTrue(r["ok"])
        self.assertEqual(r["detail"]["decision_path"], "cloud_fallback_local")
        self.assertTrue(r["offline_mode"])
        self.assertIn("timeout", r["detail"]["cloud_error"])

    def test_unknown_type_goes_cloud(self):
        r = router.route({"type": "weird"}, make_local(0.9),
                         make_cloud(label="x"), threshold=0.7)
        self.assertEqual(r["detail"]["decision_path"], "cloud")

    def test_unknown_type_cloud_fail_and_local_fail(self):
        def local(req):
            return {"ok": False, "error": "本地不认识该类型"}

        r = router.route({"type": "weird"}, local,
                         make_cloud(ok=False, error="down"), threshold=0.7)
        self.assertFalse(r["ok"])
        self.assertTrue(r["offline_mode"])
        self.assertIn("error", r)

    def test_local_exception_goes_cloud(self):
        def local(req):
            raise RuntimeError("boom")

        r = router.route({"type": "waveform"}, local, make_cloud(), threshold=0.7)
        self.assertTrue(r["ok"])
        self.assertEqual(r["detail"]["decision_path"], "cloud")

    def test_cloud_exception_fallback(self):
        def cloud(req):
            raise RuntimeError("cloud boom")

        r = router.route({"type": "waveform"}, make_local(0.5), cloud, threshold=0.7)
        self.assertTrue(r["ok"])
        self.assertEqual(r["detail"]["decision_path"], "cloud_fallback_local")
        self.assertTrue(r["offline_mode"])

    def test_elapsed_ms_present(self):
        r = router.route({"type": "waveform"}, make_local(0.9), make_cloud(),
                         threshold=0.7)
        self.assertIn("elapsed_ms", r)
        self.assertIsInstance(r["elapsed_ms"], int)

    def test_local_missing_confidence_goes_cloud(self):
        def local(req):
            return {"ok": True, "label": "sine", "detail": {}}

        r = router.route({"type": "waveform"}, local, make_cloud(), threshold=0.7)
        self.assertEqual(r["detail"]["decision_path"], "cloud")


if __name__ == "__main__":
    unittest.main()
