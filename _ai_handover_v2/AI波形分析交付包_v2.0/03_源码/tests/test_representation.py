"""视觉输入单测：形状/量化范围/确定性/三通道语义"""
import unittest

import numpy as np

from wave_ai.config import ADC_MAX, CAP_LEN, IMG, N_CHANNELS
from wave_ai.hw_sim import synth
from wave_ai.representation import COL_WIDTHS, to_images, to_model_input


class TestRepresentation(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.raw, _ = synth("square", 8, rng, chunk=8)

    def test_shape_dtype(self):
        img = to_images(self.raw)
        self.assertEqual(img.shape, (8, N_CHANNELS, IMG, IMG))
        self.assertEqual(img.dtype, np.uint8)
        self.assertEqual(int(COL_WIDTHS.sum()), CAP_LEN)

    def test_deterministic(self):
        a = to_images(self.raw)
        b = to_images(self.raw.copy())
        self.assertTrue(np.array_equal(a, b))

    def test_channel_semantics(self):
        """ch0 绝对幅度随信号幅度变化；ch2 只对"窄事件"亮，纯噪声反而暗"""
        rng = np.random.default_rng(2)
        small, _ = synth("sine", 4, rng)
        small = (small.astype(np.int32) - 512) // 6 + 512   # 幅度压到 1/6
        img_small = to_images(small.astype(np.uint16))
        self.assertLess(float(img_small[:, 0].mean()), 20.0)

        glitch, _ = synth("glitch", 8, rng)
        img_g = to_images(glitch)
        noise, _ = synth("noise", 8, rng)
        img_n = to_images(noise)
        # 毛刺：稀疏但很亮
        self.assertGreater(float(np.percentile(img_g[:, 2], 99)), 100)
        # 噪声：残差基底自适应抬高后，没有"相对基底"的窄事件 ⇒ 通道很暗
        self.assertLess(float(img_n[:, 2].mean()), 20.0)
        # 方波：边沿成亮条
        img_sq = to_images(self.raw)
        self.assertGreater(float(np.percentile(img_sq[:, 2], 99)), 80)

    def test_model_input_range(self):
        x = to_model_input(to_images(self.raw))
        self.assertEqual(x.dtype, np.float32)
        self.assertGreaterEqual(float(x.min()), -1.0)
        self.assertLessEqual(float(x.max()), 1.0)

    def test_rail_preserved_in_ch0(self):
        """撞到 0/1023 的信号，ch0 首/末行应有能量"""
        rng = np.random.default_rng(3)
        raw, _ = synth("square", 4, rng)
        raw[0, :100] = ADC_MAX
        raw[0, 100:200] = 0
        img = to_images(raw)
        self.assertGreater(float(img[0, 0, 0, :4].max()), 0)
        self.assertGreater(float(img[0, 0, -1, :4].max()), 0)


if __name__ == "__main__":
    unittest.main()
