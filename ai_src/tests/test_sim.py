"""仿真器/特征单测：物理量纲、K 覆盖、特征维度与数值健康"""
import unittest

import numpy as np

from wave_ai.config import CAP_LEN, CLASSES, LSB_TO_V
from wave_ai.features import FEAT_DIM, extract_features
from wave_ai.hw_sim import synth


class TestSimulator(unittest.TestCase):
    def test_all_classes_shape_and_range(self):
        rng = np.random.default_rng(0)
        for lab in CLASSES:
            raw, par = synth(lab, 3, rng, chunk=3)
            self.assertEqual(raw.shape, (3, CAP_LEN))
            self.assertEqual(raw.dtype, np.uint16)
            self.assertGreaterEqual(int(raw.min()), 0)
            self.assertLessEqual(int(raw.max()), 1023)

    def test_vpp_and_voltage(self):
        rng = np.random.default_rng(1)
        raw, par = synth("square", 8, rng, chunk=8)
        vpp = np.percentile(raw, 99.5, axis=1) - np.percentile(raw, 0.5, axis=1)
        # 幅值应落在 10 bit 有意义的范围（小信号 25 LSB 半幅 ~ 大信号 470）
        self.assertGreater(float(np.median(vpp)), 40)
        self.assertLess(float(np.median(vpp)), 1024)
        self.assertAlmostEqual(LSB_TO_V, 10.0 / 1024.0, places=9)

    def test_k_coverage(self):
        rng = np.random.default_rng(2)
        _, par = synth("sine", 400, rng, chunk=400)
        k = par["k"]
        self.assertGreaterEqual(float(np.nanmin(k)), 1.4)
        self.assertLessEqual(float(np.nanmax(k)), 32.5)
        # 至少一半落在演示工况 [1.5, 8]
        self.assertGreater(float(np.mean((k >= 1.5) & (k <= 8))), 0.45)

    def test_domain_shift_harder(self):
        rng = np.random.default_rng(3)
        _, a = synth("square", 200, rng, domain="train", chunk=200)
        _, b = synth("square", 200, rng, domain="hard", chunk=200)
        self.assertGreater(float(np.median(b["noise"])), float(np.median(a["noise"])))
        self.assertLess(float(np.median(b["bw"])), float(np.median(a["bw"])))


class TestFeatures(unittest.TestCase):
    def test_dim_and_finite(self):
        rng = np.random.default_rng(4)
        for lab in CLASSES:
            raw, par = synth(lab, 2, rng, chunk=2)
            for i in range(2):
                v, info = extract_features(raw[i], float(par["fs_eff"][i]))
                self.assertEqual(v.shape, (FEAT_DIM,))
                self.assertTrue(np.all(np.isfinite(v)))
                self.assertIsInstance(info, dict)

    def test_local_probs_used(self):
        rng = np.random.default_rng(5)
        raw, par = synth("square", 1, rng, chunk=1)
        lp = np.zeros(16)
        lp[1] = 1.0
        v0, _ = extract_features(raw[0], 2e6, None)
        v1, _ = extract_features(raw[0], 2e6, lp)
        self.assertAlmostEqual(float(v0[-1]), 0.0)     # lp_available
        self.assertAlmostEqual(float(v1[-1]), 1.0)
        self.assertGreater(float(v1[-17 + 1]), 0.5)    # square 的概率位

    def test_frequency_of_known_sine(self):
        rng = np.random.default_rng(6)
        n = 4096
        fs = 2e6
        k = 7.0
        x = 511.5 + 400 * np.sin(2 * np.pi * k * np.arange(n) / n)
        x = np.clip(np.rint(x), 0, 1023)
        v, info = extract_features(x, fs)
        self.assertAlmostEqual(info["K"], k, delta=0.1)
        self.assertAlmostEqual(info["freq_hz"], k * fs / n, delta=0.02 * k * fs / n)


if __name__ == "__main__":
    unittest.main()
