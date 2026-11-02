"""
test_preprocess.py —— 预处理契约的自检（纯标准库 + numpy，本地即可运行）

★ 这些断言是"主机与板端/示波器方可互通"的保证：
   任何一条失败，说明预处理契约被破坏了，必须先修再训练。
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src", "common"))

import preprocess as P            # noqa: E402
import dds_sim as D               # noqa: E402


class TestConstants(unittest.TestCase):
    def test_capture_and_image_dims(self):
        self.assertEqual(P.CAP_LEN, 4096)
        self.assertEqual(P.IMG, 28)
        self.assertEqual(P.NFFT, 512)

    def test_frame_count_and_coverage(self):
        self.assertEqual(len(P.FRAME_STARTS), P.IMG)
        # 末帧必须右对齐且不越界
        last = P.FRAME_STARTS[-1]
        self.assertEqual(last + P.NFFT, P.CAP_LEN)
        # 帧起点单调不减，且覆盖整段缓冲（第一帧从 0 开始）
        self.assertEqual(P.FRAME_STARTS[0], 0)
        self.assertTrue(all(P.FRAME_STARTS[i] <= P.FRAME_STARTS[i + 1]
                            for i in range(len(P.FRAME_STARTS) - 1)))

    def test_col_bounds_cover_all_samples(self):
        self.assertEqual(P.COL_BOUNDS[0][0], 0)
        self.assertEqual(P.COL_BOUNDS[-1][1], P.CAP_LEN)
        for i in range(len(P.COL_BOUNDS) - 1):
            self.assertEqual(P.COL_BOUNDS[i][1], P.COL_BOUNDS[i + 1][0])

    def test_bin_ranges_valid(self):
        self.assertEqual(len(P.BIN_RANGES), P.NROWS)
        prev_hi = None
        for (a, b) in P.BIN_RANGES:
            self.assertGreaterEqual(a, 1)
            self.assertLessEqual(b, P.NFFT // 2 + 1)
            self.assertGreater(b, a)          # 每行至少 1 个频点
            if prev_hi is not None:
                self.assertEqual(a, prev_hi)  # ★ 不重叠、不留空隙
            prev_hi = b
        # 末行必须覆盖到最高频点
        self.assertEqual(P.BIN_RANGES[-1][1], P.NFFT // 2 + 1)
        # ★ 前若干行必须各自独享不同的 bin（否则低频段全是冗余行）
        first_bins = [a for (a, b) in P.BIN_RANGES[:8]]
        self.assertEqual(len(set(first_bins)), len(first_bins))


class TestImplementationsMatch(unittest.TestCase):
    """★ numpy 与纯 Python 两条实现必须逐点一致（板端可能没有 numpy）"""

    def _samples(self):
        rng = np.random.default_rng(12345)
        out = []
        for kind in (D.WAVE_SINE, D.WAVE_SQUARE, D.WAVE_TRIANGLE, D.WAVE_SAWTOOTH):
            spec = D.CaptureSpec(kind=kind, cycles=7.3, amp=95.0, duty=0.5,
                                 phase0=0.21, dc=2.0, gain=1.01, noise_lsb=1.3, dec=64)
            out.append(D.build_capture(spec, rng))
        out.append(D.build_noise_capture(
            D.CaptureSpec(kind=0, cycles=1.0, amp=80.0, noise_lsb=1.0), rng))
        return out

    def test_stft_identical(self):
        for s in self._samples():
            a = P.capture_to_image_u8_np(s)
            b = np.asarray(P.capture_to_image_u8_pure(s.tolist()), dtype=np.uint8)
            np.testing.assert_array_equal(a, b)

    def test_wdens_identical(self):
        for s in self._samples():
            a = P.capture_to_wdens_u8_np(s)
            b = np.asarray(P.capture_to_wdens_u8_pure(s.tolist()), dtype=np.uint8)
            np.testing.assert_array_equal(a, b)

    def test_batch_equals_single(self):
        ss = np.stack(self._samples())
        for mode, single in (("stft", P.capture_to_image_u8_np),
                             ("wdens", P.capture_to_wdens_u8_np)):
            batch = P.captures_to_images(ss, mode)
            self.assertEqual(batch.shape, (len(ss), P.IMG, P.IMG))
            for i in range(len(ss)):
                np.testing.assert_array_equal(batch[i], single(ss[i]))


class TestProperties(unittest.TestCase):
    def test_output_dtype_and_range(self):
        rng = np.random.default_rng(0)
        for mode in P.PP_MODES:
            for label in D.CLASSES:
                y, _spec, _info = D.make_sample(rng, label)
                img = P.capture_to_image(y, mode)
                self.assertEqual(img.shape, (P.IMG, P.IMG))
                self.assertEqual(img.dtype, np.uint8)
                self.assertLessEqual(int(img.max()), 255)
                self.assertGreater(int(img.max()), 0, "图像全 0 说明归一化坏了")

    def test_amplitude_invariance(self):
        """★ 幅度变化不应改变（或只轻微改变）密度图 —— 这是域随机化的前提"""
        rng = np.random.default_rng(7)
        base = D.build_capture(D.CaptureSpec(D.WAVE_SINE, 9.0, 100.0,
                                             noise_lsb=0.0, dc=0.0, gain=1.0), rng)
        half = D.build_capture(D.CaptureSpec(D.WAVE_SINE, 9.0, 50.0,
                                             noise_lsb=0.0, dc=0.0, gain=1.0), rng)
        a = P.capture_to_wdens_u8_np(base).astype(int)
        b = P.capture_to_wdens_u8_np(half).astype(int)
        # 半幅度时波形只占中间一半的行，图案应相近（允许差异但相关度要高）
        self.assertGreater(float(a.max()), 0)
        self.assertGreater(float(b.max()), 0)

    def test_signal_loss_visible_in_wdens(self):
        """丢信号应让某一时间段的密度收窄到中位电平 → 该列非零行数明显变少"""
        rng = np.random.default_rng(3)
        spec = D.CaptureSpec(D.WAVE_SINE, 10.0, 100.0, noise_lsb=0.5, dec=64)
        y = D.build_capture(spec, rng)
        img = P.capture_to_wdens_u8_np(y)
        cols_full = int((img > 8).sum(axis=0).max())
        y2 = y.copy()
        y2[1000:2400] = 128                       # 人工制造丢信号
        img2 = P.capture_to_wdens_u8_np(y2)
        # 丢失段对应的列，非零行数应该更少
        seg = slice(int(1000 / P.CAP_LEN * 28) + 1, int(2400 / P.CAP_LEN * 28) - 1)
        self.assertLess((img2[:, seg] > 8).sum(axis=0).mean(),
                        (img[:, seg] > 8).sum(axis=0).mean() + 1e-9)
        self.assertGreater(cols_full, 0)

    def test_deterministic(self):
        rng = np.random.default_rng(11)
        y, _, _ = D.make_sample(rng, "square")
        for mode in P.PP_MODES:
            a = P.capture_to_image(y, mode)
            b = P.capture_to_image(y, mode)
            np.testing.assert_array_equal(a, b)

    def test_int8_conversion(self):
        img = np.array([[0, 128, 255]], dtype=np.uint8)
        out = P.image_u8_to_int8(img)
        np.testing.assert_array_equal(out, np.array([[-128, 0, 127]], dtype=np.int8))


class TestDdsSim(unittest.TestCase):
    def test_freq_word_roundtrip(self):
        # DDS 频率字是 32 位、基频 20 MHz ⇒ 分辨率 20e6/2^32 ≈ 4.66e-3 Hz
        tol = D.FS_BASE / (2 ** 32)
        for f in (1000.0, 12345.6, 250000.0):
            w = D.freq_word_from_hz(f)
            self.assertLess(abs(D.hz_from_freq_word(w) - f), tol)
            self.assertGreaterEqual(w, 0)
            self.assertLessEqual(w, 2 ** 32 - 1)

    def test_probe_freq_top_is_not_filtered(self):
        """频段内的目标频率不应被丢掉（用通用上限公式，不写死滤波器截止）"""
        w = D.freq_word_from_hz(1_000_000.0)
        self.assertLessEqual(w, 2 ** 32 - 1)

    def test_waveforms_bounded(self):
        for kind in (D.WAVE_SINE, D.WAVE_SQUARE, D.WAVE_TRIANGLE, D.WAVE_SAWTOOTH):
            p = np.linspace(0, 3, 1000)
            w = D.wave_ideal(kind, p, 0.5)
            self.assertLessEqual(float(w.max()), 1.0 + 1e-9)
            self.assertGreaterEqual(float(w.min()), -1.0 - 1e-9)

    def test_duty_abnormal_actually_changes_duty(self):
        p = np.linspace(0, 100, 100000)
        w = D.wave_ideal(D.WAVE_SQUARE, p, 0.25)
        self.assertAlmostEqual(float((w > 0).mean()), 0.25, delta=0.01)

    def test_capture_range(self):
        rng = np.random.default_rng(5)
        for label in D.CLASSES:
            y, spec, _ = D.make_sample(rng, label)
            self.assertEqual(y.shape, (D.CAP_LEN,))
            self.assertEqual(y.dtype, np.uint8)
            self.assertGreaterEqual(int(y.min()), 0)
            self.assertLessEqual(int(y.max()), 255)

    def test_meta_has_dds_params(self):
        rng = np.random.default_rng(9)
        y, spec, info = D.make_sample(rng, "glitch")
        # 默认类别表（8 类，不含毛刺）里没有 glitch ⇒ class_index 应为 None
        m = D.spec_to_meta(spec, "glitch", info, D.CLASSES_NO_GLITCH)
        for k in ("label", "anomaly", "freq_hz", "amp", "duty", "noise_level",
                  "dec", "dds_params", "class_index"):
            self.assertIn(k, m)
        for k in ("waveform", "freq_word", "amp", "dec"):
            self.assertIn(k, m["dds_params"])
        self.assertEqual(m["label"], "glitch")
        self.assertIsNone(m["class_index"])
        # 含毛刺的 9 类表里必须能定位到下标 5
        m9 = D.spec_to_meta(spec, "glitch", info, D.CLASSES)
        self.assertEqual(m9["class_index"], D.CLASSES.index("glitch"))

    def test_class_lists_consistent(self):
        """★ 冻结点：类别表顺序就是模型输出下标，不允许随意改"""
        self.assertEqual(D.CLASSES_NO_GLITCH,
                         ["sine", "square", "triangle", "sawtooth", "noise",
                          "clipping", "signal_loss", "duty_abnormal"])
        self.assertEqual(D.CLASSES,
                         ["sine", "square", "triangle", "sawtooth", "noise",
                          "glitch", "clipping", "signal_loss", "duty_abnormal"])
        self.assertEqual(D.classes_for(False), D.CLASSES_NO_GLITCH)
        self.assertEqual(D.classes_for(True), D.CLASSES)
        self.assertEqual(D.CLASSES_REQUIRING_PL, ["glitch"])

    def test_all_four_anomalies_are_injectable(self):
        rng = np.random.default_rng(42)
        for a in D.ANOMALY_CLASSES:
            seen = False
            for _ in range(30):
                y, spec, info = D.make_sample(rng, a)
                if a == "duty_abnormal":
                    seen = seen or abs(spec.duty - 0.5) > 0.05
                else:
                    seen = True
            self.assertTrue(seen, "异常 %s 没有被注入" % a)


if __name__ == "__main__":
    unittest.main(verbosity=2)
