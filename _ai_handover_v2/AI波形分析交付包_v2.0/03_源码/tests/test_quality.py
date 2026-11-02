"""质量评估单测：已知边沿的精度、不可测项必须为 null、评分范围"""
import unittest

import numpy as np

from wave_ai.quality import analyze_quality


def filtered_square(bw=0.5, noise=1.5, cycles=4.0, seed=0):
    from scipy.signal import butter, sosfilt
    rng = np.random.default_rng(seed)
    n = 4096
    t = np.arange(n) * cycles / n
    w = np.where(np.mod(t, 1.0) < 0.5, 1.0, -1.0)
    x = 511.5 + 250.0 * w
    x = sosfilt(butter(2, bw, "low", output="sos"), x)
    x = np.clip(np.rint(x + rng.normal(0, noise, n)), 0, 1023)
    return x


class TestQuality(unittest.TestCase):
    def test_rise_time_accuracy(self):
        """10~90% 上升时间：采样间隔 0.5 µs，插值误差应 < 0.5 µs"""
        from scipy.signal import butter, sosfilt
        fs, fs_hi = 2e6, 200e6
        for bw in (0.35, 0.6, 0.85):
            step = np.zeros(400000)
            step[100000:] = 1.0
            y = sosfilt(butter(2, bw * fs / fs_hi, "low", output="sos"), step)
            true_us = (np.argmax(y >= 0.9) - np.argmax(y >= 0.1)) / fs_hi * 1e6
            q = analyze_quality(filtered_square(bw=bw), dec=10, label="square")
            self.assertIsNotNone(q["rise_us"])
            self.assertLess(abs(q["rise_us"] - true_us), 0.5,
                            "bw=%.2f 实测 %.2f 真值 %.2f" % (bw, q["rise_us"], true_us))

    def test_null_when_not_measurable(self):
        """噪声/丢信号不谈质量；先说明再返回 null，不编数字"""
        from wave_ai.hw_sim import synth
        rng = np.random.default_rng(0)
        raw, _ = synth("noise", 2, rng)
        q = analyze_quality(raw[0], dec=10, label="noise")
        self.assertFalse(q["applicable"])
        self.assertIsNone(q["score"])
        self.assertIn("不评估质量", " ".join(q["notes"]))

    def test_score_range_and_components(self):
        q = analyze_quality(filtered_square(), dec=10, label="square")
        self.assertTrue(q["applicable"])
        self.assertIsNotNone(q["score"])
        self.assertGreaterEqual(q["score"], 0)
        self.assertLessEqual(q["score"], 100)
        self.assertGreater(q["coverage"], 0.5)
        self.assertIsNotNone(q["snr_db"])
        self.assertIsNotNone(q["shape_fidelity"])

    def test_noise_degrades_score(self):
        """噪声越大，SNR 与综合评分都应下降（单调性）"""
        prev = None
        for noise in (1.0, 8.0, 25.0):
            q = analyze_quality(filtered_square(noise=noise), dec=10, label="square")
            if prev is not None:
                self.assertLess(q["snr_db"], prev["snr_db"] + 1e-9)
            prev = q

    def test_thd_of_sine_is_small(self):
        rng = np.random.default_rng(0)
        n = 4096
        x = 511.5 + 300 * np.sin(2 * np.pi * 5.37 * np.arange(n) / n)
        x = np.clip(np.rint(x + rng.normal(0, 0.5, n)), 0, 1023)
        q = analyze_quality(x, dec=10, label="sine")
        self.assertLess(q["thd_pct"], 3.0)
        # 非跳变类不报上升时间
        self.assertIsNone(q["rise_us"])


if __name__ == "__main__":
    unittest.main()
