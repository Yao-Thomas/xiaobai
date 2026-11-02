"""契约单测：结构、长度、顺序、文本约束（需要已训练模型；没有则跳过）"""
import os
import unittest

import numpy as np

from wave_ai.config import CAP_LEN, CLASSES, CLASSES_8

MODEL = os.environ.get("WAVE_MODEL", "runs/v2_full/model_bundle.pt")
ANOM = os.environ.get("WAVE_ANOMALY", "runs/v2_full/anomaly_stats.npz")


def _analyzer():
    from wave_ai.analyzer import Analyzer
    return Analyzer(MODEL, ANOM if os.path.exists(ANOM) else None)


@unittest.skipUnless(os.path.exists(MODEL), "未找到模型 %s" % MODEL)
class TestContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = _analyzer()

    def _payload(self, label="square", dec=10):
        from wave_ai.hw_sim import synth
        rng = np.random.default_rng(3)
        raw, par = synth(label, 1, rng)
        probs = [0.0] * 8
        probs[CLASSES_8.index(label) if label in CLASSES_8 else 0] = 0.8
        probs[(CLASSES_8.index(label) + 1) % 8 if label in CLASSES_8 else 1] = 0.2
        return {
            "type": "waveform_analysis",
            "samples": [int(v) for v in raw[0].tolist()],
            "fs": 20000000, "dec": int(par["dec"][0]),
            "local_cnn": {"label": "square", "confidence": 0.8,
                          "classes": CLASSES_8, "probs": probs},
            "options": {"max_chars": 70, "for_voice": True,
                        "want_quality": True, "want_anomaly": True},
        }

    def test_analyze_structure(self):
        r = self.a.analyze(self._payload())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(len(r["classes"]), len(r["probs"]))
        self.assertEqual(r["classes"][:8], CLASSES_8)
        self.assertAlmostEqual(sum(r["probs"]), 1.0, places=3)
        i = int(np.argmax(r["probs"]))
        self.assertEqual(r["classes"][i], r["label"])
        self.assertAlmostEqual(r["confidence"], r["probs"][i], places=4)
        self.assertLessEqual(len(r["text"]), 70)
        self.assertTrue(r["text"].endswith("。"))
        for ch in "*#`[]{}|~^":
            self.assertNotIn(ch, r["text"])
        self.assertIn("score", r["quality"])
        self.assertIn("is_anomaly", r["anomaly"])
        self.assertLess(r["elapsed_ms"], 800)

    def test_health(self):
        h = self.a.health()
        self.assertTrue(h["ok"])
        self.assertEqual(h["input"], "samples")
        self.assertEqual(len(h["classes"]), 16)

    def test_classify_endpoint(self):
        r = self.a.classify(self._payload())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["engine"], "vision_v2")
        self.assertEqual(len(r["classes"]), len(r["probs"]))

    def test_explain_endpoint(self):
        r = self.a.explain({
            "type": "waveform_analysis",
            "result": {"label": "square", "label_cn": "方波", "confidence": 0.97,
                       "measurements": {"freq_hz": 998.5, "vpp_v": 1.008,
                                        "duty_pct": 49.9},
                       "quality": {"score": 87, "snr_db": 42.0}},
            "style": {"max_chars": 70, "for_voice": True},
        })
        self.assertTrue(r["ok"], r.get("error"))
        self.assertLessEqual(len(r["text"]), 70)
        self.assertTrue(r["tts_ready"])

    def test_bad_input_returns_ok_false(self):
        for body in ({}, {"samples": [1, 2, 3]},
                     {"samples": [2000] * CAP_LEN}):
            r = self.a.analyze(body)
            self.assertFalse(r["ok"])
            self.assertTrue(r.get("error"))

    def test_constant_input_is_valid(self):
        """全 999 是合法 10 bit 常量，应正常返回（不能把"平线"当错误）"""
        r = self.a.analyze({"samples": [999] * CAP_LEN, "dec": 10})
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIn(r["label"], CLASSES)

    def test_ac3_custom_max_chars(self):
        p = self._payload()
        p["options"]["max_chars"] = 40
        r = self.a.analyze(p)
        self.assertTrue(r["ok"])
        self.assertLessEqual(len(r["text"]), 40)


if __name__ == "__main__":
    unittest.main()
