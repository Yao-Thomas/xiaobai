"""
test_qmodel.py —— ★ 量化模型与硬件同构性的验证（需要 torch；在 lab415 上跑）

这是本项目最重要的一组断言：
    「torch 上的整数量化前向」 必须与 「numpy 复刻的 HLS 循环」 **逐点完全一致**。
    只有这一条成立，导出的 reference_out.bin 才能作为板子侧的比对基准。

对应硬件源码：
    src/hls/cnn_conv_pool_q.cpp  ——  (acc*MFQ)>>16, clamp[0,127], 融合 2×2 maxpool
    src/hls/cnn_fc_q.cpp         ——  (acc*MFQ)>>16, clamp[-128,127]
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import torch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src", "common"))

import qmodel as Q            # noqa: E402


def fresh_model(seed=0, n_classes=9):
    """构造一个"已校准"的量化模型（不训练，只测数值一致性）"""
    torch.manual_seed(seed)
    m = Q.QWaveNet(n_classes=n_classes)
    with torch.no_grad():
        for mod in (m.conv1, m.conv2, m.fc):
            mod.weight.mul_(torch.rand(1).item() * 0.5 + 0.15)
    m.set_activations_warm(False)
    m.init_all_scales()
    xcal = torch.from_numpy(
        np.random.default_rng(seed).integers(0, 256, size=(256, 1, Q.IMG, Q.IMG))
    ).float()
    m.calibrate(xcal, iters=3)
    m.eval()
    return m


QWaveNet_factory = Q.QWaveNet


class TestTorchEqualsNumpy(unittest.TestCase):
    """★ 核心：torch 整数前向 == numpy 硬件复刻"""

    def test_logits_identical(self):
        m = fresh_model(0)
        rng = np.random.default_rng(1)
        iw = m.int_weights()
        w1 = iw["conv1.weight"].numpy()
        w2 = iw["conv2.weight"].numpy()
        wf = iw["fc.weight"].numpy()
        mfq = m.mfq_list()
        for k in range(24):
            x = rng.integers(0, 256, size=(Q.IMG, Q.IMG)).astype(np.uint8)
            lg_np, f1_np, f2_np = Q.reference_infer_arrays(x, w1, w2, wf, mfq)
            out = m.quant_forward(torch.from_numpy(x[None, None]).float())
            lg_t = out["logits"][0].detach().numpy()
            np.testing.assert_array_equal(
                lg_t.astype(np.int64), lg_np.astype(np.int64),
                err_msg="第 %d 个样本 logits 不一致: torch=%s numpy=%s" % (k, lg_t, lg_np))
            np.testing.assert_array_equal(
                out["f1"][0].detach().numpy().astype(np.int64),
                f1_np.astype(np.int64), err_msg="f1 不一致")
            np.testing.assert_array_equal(
                out["f2"][0].detach().numpy().astype(np.int64),
                f2_np.astype(np.int64), err_msg="f2 不一致")

    def test_identical_in_full_range_input(self):
        """输入取极端值（0 与 255）时也要一致 —— 这是 clamp 边界最容易出错的点"""
        m = fresh_model(2)
        iw = m.int_weights()
        w1, w2, wf = (iw["conv1.weight"].numpy(), iw["conv2.weight"].numpy(),
                      iw["fc.weight"].numpy())
        mfq = m.mfq_list()
        for val in (0, 1, 127, 128, 254, 255):
            x = np.full((Q.IMG, Q.IMG), val, dtype=np.uint8)
            lg_np, _, _ = Q.reference_infer_arrays(x, w1, w2, wf, mfq)
            lg_t = m.quant_forward(torch.from_numpy(x[None, None]).float())["logits"][0]
            np.testing.assert_array_equal(lg_t.detach().numpy().astype(np.int64),
                                          lg_np.astype(np.int64),
                                          err_msg="常量输入 %d 不一致" % val)

    def test_matches_with_random_mfq(self):
        """任意 MFQ 组合都要一致（板端可能传别的值）"""
        m = fresh_model(3)
        iw = m.int_weights()
        w1, w2, wf = (iw["conv1.weight"].numpy(), iw["conv2.weight"].numpy(),
                      iw["fc.weight"].numpy())
        rng = np.random.default_rng(5)
        x = rng.integers(0, 256, size=(Q.IMG, Q.IMG)).astype(np.uint8)
        for mfq in ([119, 119, 119], [1, 1, 1], [255, 64, 8], [64, 128, 200],
                    [1000, 1000, 1000]):
            lg_np, _, _ = Q.reference_infer_arrays(x, w1, w2, wf, mfq)
            lg_t = m.quant_forward(torch.from_numpy(x[None, None]).float(),
                                   mfq_override=mfq)["logits"][0]
            np.testing.assert_array_equal(lg_t.detach().numpy().astype(np.int64),
                                          lg_np.astype(np.int64),
                                          err_msg="MFQ=%s 不一致" % mfq)

    def test_batch_equals_single(self):
        m = fresh_model(4)
        rng = np.random.default_rng(7)
        xs = rng.integers(0, 256, size=(8, 1, Q.IMG, Q.IMG)).astype(np.uint8)
        out = m.quant_forward(torch.from_numpy(xs).float())["logits"].detach().numpy()
        for i in range(len(xs)):
            one = m.quant_forward(torch.from_numpy(xs[i:i + 1]).float())["logits"]
            np.testing.assert_array_equal(out[i].astype(np.int64),
                                          one[0].detach().numpy().astype(np.int64))


class TestQuantPrimitives(unittest.TestCase):
    def test_requant_is_arithmetic_shift(self):
        """(acc*MFQ)>>16 对负数必须是向下取整（算术右移），不是截断"""
        acc = np.array([-1, -65536, -65537, 0, 65535, 65536, 131072], dtype=np.int64)
        q = Q.requant_shift(acc, 1, relu=False)
        expect = acc >> 16
        np.testing.assert_array_equal(q.astype(np.int64), expect)

    def test_relu_clamp(self):
        acc = np.array([-1000000, -1, 0, 127 << 16, 200 << 16], dtype=np.int64)
        q = Q.requant_shift(acc, 1, relu=True)
        self.assertEqual(int(q[0]), 0)
        self.assertEqual(int(q[1]), 0)
        self.assertEqual(int(q[2]), 0)
        self.assertEqual(int(q[3]), 127)
        self.assertEqual(int(q[4]), 127)      # 饱和而不是回绕

    def test_fc_clamp_both_sides(self):
        acc = np.array([-1000 << 16, 1000 << 16], dtype=np.int64)
        q = Q.requant_shift(acc, 1, relu=False)
        self.assertEqual(int(q[0]), -128)
        self.assertEqual(int(q[1]), 127)

    def test_int32_wrap_emulation(self):
        """★ HLS 里 acc*MFQ 是 ap_int<32>，溢出会回绕；参考实现必须同样回绕"""
        acc = np.array([2 ** 30], dtype=np.int64)
        mfq = 4
        raw = int(acc[0]) * mfq                      # 2^32 -> 回绕成 0
        self.assertEqual(int(Q.wrap_int32(np.array([raw]))[0]), 0)
        q = Q.requant_shift(acc, mfq, relu=False)
        self.assertEqual(int(q[0]), 0)

    def test_maxpool_matches_torch(self):
        import torch
        rng = np.random.default_rng(0)
        f = rng.integers(0, 128, size=(3, 8, 8)).astype(np.int32)
        np_out = Q.maxpool2_int8(f)
        t_out = torch.nn.functional.max_pool2d(
            torch.from_numpy(f.astype(np.float32))[None], 2, 2)[0].numpy()
        np.testing.assert_array_equal(np_out.astype(np.int64), t_out.astype(np.int64))

    def test_conv_matches_torch(self):
        import torch
        rng = np.random.default_rng(1)
        x = rng.integers(-128, 128, size=(2, 9, 9)).astype(np.int32)
        w = rng.integers(-127, 128, size=(4, 2, 3, 3)).astype(np.int32)
        np_acc = Q.im2col_conv_int8(x, w)
        t_acc = torch.nn.functional.conv2d(
            torch.from_numpy(x.astype(np.float32))[None],
            torch.from_numpy(w.astype(np.float32)))[0].numpy()
        np.testing.assert_array_equal(np_acc.astype(np.int64), t_acc.astype(np.int64))

    def test_weight_index_order(self):
        """★ 权重索引顺序必须与 HLS 一致：w[(oc*IN_CH+ic)*KH*KW + ky*KW + kx]"""
        rng = np.random.default_rng(2)
        w = rng.integers(-127, 128, size=(2, 2, 3, 3)).astype(np.int32)
        # HLS 的下标公式显式重排后应与 im2col_conv_int8 的 (OC,IC,K,K) 解释一致
        x = rng.integers(-128, 128, size=(2, 6, 6)).astype(np.int32)
        acc_ref = Q.im2col_conv_int8(x, w)
        # 手工按 HLS 公式累加
        OC, IC, KH, KW = 2, 2, 3, 3
        wflat = w.reshape(-1)
        OH = OW = 6 - 3 + 1
        acc_man = np.zeros((OC, OH, OW), dtype=np.int64)
        for oc in range(OC):
            for oy in range(OH):
                for ox in range(OW):
                    s = 0
                    for ic in range(IC):
                        for ky in range(KH):
                            for kx in range(KW):
                                s += int(x[ic, oy + ky, ox + kx]) * int(
                                    wflat[(oc * IC + ic) * KH * KW + ky * KW + kx])
                    acc_man[oc, oy, ox] = s
        np.testing.assert_array_equal(acc_ref, acc_man)


class TestDiagnostics(unittest.TestCase):
    def test_mfq_positive_and_headroom(self):
        m = fresh_model(6)
        mfq = m.mfq_list()
        self.assertEqual(len(mfq), 3)
        for v in mfq:
            self.assertGreater(v, 0, "MFQ 必须为正整数")
        diag = Q.diagnose(m, torch.from_numpy(
            np.random.default_rng(0).integers(0, 256, size=(256, 1, Q.IMG, Q.IMG))
        ).float())
        self.assertIn("saturation_frac", diag)
        self.assertIn("acc_times_mfq", diag)
        # ★ 不允许溢出
        for v, risk in zip(diag["acc_times_mfq"], diag["overflow_risk"]):
            self.assertFalse(risk, "acc*MFQ=%.0f 超出 int32，硬件会回绕" % v)

    def test_weights_within_int8(self):
        m = fresh_model(7)
        for k, v in m.int_weights().items():
            self.assertLessEqual(int(v.abs().max()), 127, "%s 超出 int8" % k)
            self.assertGreater(int(v.abs().max()), 0, "%s 全 0" % k)


if __name__ == "__main__":
    unittest.main(verbosity=2)
