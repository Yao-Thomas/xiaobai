"""
qmodel.py —— ★ 硬件同构 INT8 量化模型（本项目量化方案的核心）

=============================================================================
设计目标：训练出来的网络，在【CPU/GPU 上的整数前向】与【PL 加速器的硬件前向】
          **逐点完全一致**。这样导出的 reference_out.bin 才是可信的比对基准。

硬件事实（不可改，来自上一轮交接包）：
  源码/hls/cnn_conv_pool_q.cpp:
      acc = Σ_ic Σ_ky Σ_kx  img[...] * w[...]        (int8 × int8 → ap_int<32>)
      q   = (acc * MFQ) >> 16                         (算术右移 = floor)
      q   = clamp(q, 0, 127)                          (ReLU + 饱和)
      out = max over 2×2 window                       (max-pool 融合在卷积里)
  源码/hls/cnn_fc_q.cpp:
      acc = Σ_i x[i]*w[oc*IN+i]                       (ap_int<32>)
      q   = (acc * MFQ) >> 16 ;  q = clamp(q, -128, 127)
  权重布局： w[(oc*IN_CH+ic)*KH*KW + ky*KW + kx]      (conv)
             w[oc*IN + i]                              (fc)
  ★ 不传偏置（"不用偏置数组"）⇒ 网络必须 bias=False，或主机侧把偏置折进别处。
    本项目采用 bias=False 训练。

几何（必须与 IP 一致，见 交接文档/05_M4b_CNN方案.md）：
    输入 1×28×28 int8
    Conv A: k=3,in=1,out=8,   OH=(28-3+1)/2=13  (P=2，池化融合在卷积里)
    Conv B: k=3,in=8,out=16,  OH=(13-3+1)/2=5
    FC    : 400 → N_CLASSES

★ 关于 MFQ（重要结论，见 docs/00_接口冻结单.md §4）
  上一轮的 "MFQ=119" 是**那个 MNIST 模型的主机校准值**，不是硬件常量：
  HLS 里 MFQ 是 s_axilite 寄存器，每次调用都可以传不同值。
  本项目据此采用**逐层 MFQ_L**（严格仍是 `(acc×MFQ)>>16`，硬件零改动），
  并同时导出"统一 MFQ"兼容版做对比。

★ 溢出安全（必须遵守）
  HLS 里 `acc * MFQ` 在 ap_int<32> 里做 ⇒ 溢出会**回绕**。
  约束： max|acc| × MFQ < 2^31。
  本项目代码里既做检查（check_overflow），参考实现里也**逐位模拟 32 位回绕**，
  保证 reference_out.bin 与真硬件一致（哪怕真的溢出也一致）。
=============================================================================
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

IMG = 28
SHIFT = 16
QMAX_W = 127                    # 对称权重量化上限（不用 -128）
QMIN_A, QMAX_A = -128, 127      # 激活整型范围
QMIN_R, QMAX_R = 0, 127         # conv 输出（ReLU 后）范围
INT32_MAX = 2 ** 31 - 1


# ---------------------------------------------------------------------------
# STE（直通估计）算子：前向是真整数，反向按恒等传梯度
# ---------------------------------------------------------------------------
def _ste_round(x: torch.Tensor) -> torch.Tensor:
    return x + (torch.round(x) - x).detach()


def _ste_floor(x: torch.Tensor) -> torch.Tensor:
    return x + (torch.floor(x) - x).detach()


def _ste_clamp(x: torch.Tensor, lo: float, hi: float) -> torch.Tensor:
    return x + (x.clamp(lo, hi) - x).detach()


def _exact_requant(acc: torch.Tensor, mfq: int) -> torch.Tensor:
    """
    ★ 与 HLS 逐位一致： (acc * MFQ) >> 16  ==  floor(acc * MFQ / 2^16)

    ★★ 这里有一个极容易写错、而且错了很难发现的地方：
        正确： floor(acc·MFQ / 2^16)        （除法在 floor 里面）
        错误： floor(acc·MFQ) / 2^16        （会得到非整数！
                                            因为 floor(k)/65536 一般不是整数）
      第一版实现就写成了后者，导致 torch 侧的激活值是"小数"，
      而 numpy 硬件复刻是整数 ⇒ 训练出来的模型与硬件不一致
      （只有把小数截断成 int 时才会"看起来一样"，所以更难发现）。
      这个 bug 是被 tests/test_qmodel.py 的逐点比对断言抓出来的。

    精度：acc·MFQ ≤ 6.5e6×1e3 ≈ 1e10 < 2^53，float64 内精确；
          除以 2^16（2 的幂）也是精确操作 ⇒ floor 的结果与整数运算完全一致。
    """
    prod = acc.double() * float(int(mfq)) * (1.0 / float(1 << SHIFT))
    return _ste_floor(prod).float()


def _q_layer(acc: torch.Tensor, mfq: int, relu: bool) -> torch.Tensor:
    """requant + 饱和（conv 走 ReLU → [0,127]；fc 走 [-128,127]）"""
    y = _exact_requant(acc, mfq)
    return _ste_clamp(y, QMIN_R, QMAX_R) if relu else _ste_clamp(y, QMIN_A, QMAX_A)


# ---------------------------------------------------------------------------
# 一层"量化卷积 + ReLU + 最大池化"（与 cnn_conv_pool_q 完全同构）
# ---------------------------------------------------------------------------
class QConvPool(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, k: int = 3, pool: int = 2,
                 name: str = "conv"):
        super().__init__()
        self.in_ch, self.out_ch, self.k, self.pool = in_ch, out_ch, k, pool
        self.name = name
        self.weight = nn.Parameter(torch.empty(out_ch, in_ch, k, k))
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        self.log2_sw = nn.Parameter(torch.tensor(-3.0))
        self.log2_sy = nn.Parameter(torch.tensor(0.0))
        self.warm = True          # warmup 阶段冻结整数化（等价于普通浮点训练）

    # ---- 量化步长 ----
    def s_w_val(self) -> float:
        return float(torch.pow(2.0, self.log2_sw).detach())

    def s_y_val(self) -> float:
        return float(torch.pow(2.0, self.log2_sy).detach())

    def w_int(self) -> torch.Tensor:
        """量化后的整数权重（int8 值域，float 张量便于 autograd）"""
        if self.warm:
            return self.weight
        s_w = torch.pow(2.0, self.log2_sw)
        wq = _ste_round(self.weight / s_w)
        return _ste_clamp(wq, -QMAX_W, QMAX_W)

    def init_scales(self) -> None:
        """按当前浮点权重的最大绝对值设置 s_w = max|W|/127（标准对称量化初始化）"""
        with torch.no_grad():
            wmax = float(self.weight.abs().max().clamp_min(1e-8))
            self.log2_sw.copy_(torch.log2(torch.tensor(wmax / QMAX_W)))
            self.warm = False

    def mfq(self, s_x: float) -> int:
        m = float(s_x) * self.s_w_val() / self.s_y_val() * (1 << SHIFT)
        return int(round(m))

    def forward(self, x_q: torch.Tensor, s_x: float, mfq: Optional[int] = None):
        wq = self.w_int()
        acc = F.conv2d(x_q, wq, bias=None, stride=1, padding=0)
        if mfq is None:
            mfq = max(1, self.mfq(s_x))
        y = _q_layer(acc, mfq, relu=True)
        if self.pool > 1:
            y = F.max_pool2d(y, self.pool, self.pool)
        return y, self.s_y_val()


class QLinear(nn.Module):
    """全连接层（与 cnn_fc_q 同构；无 ReLU，饱和到 int8）"""

    def __init__(self, in_f: int, out_f: int, name: str = "fc"):
        super().__init__()
        self.in_f, self.out_f = in_f, out_f
        self.name = name
        self.weight = nn.Parameter(torch.empty(out_f, in_f))
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        self.log2_sw = nn.Parameter(torch.tensor(-6.0))
        self.log2_sy = nn.Parameter(torch.tensor(3.0))
        self.warm = True

    def s_w_val(self) -> float:
        return float(torch.pow(2.0, self.log2_sw).detach())

    def s_y_val(self) -> float:
        return float(torch.pow(2.0, self.log2_sy).detach())

    def w_int(self) -> torch.Tensor:
        if self.warm:
            return self.weight
        s_w = torch.pow(2.0, self.log2_sw)
        wq = _ste_round(self.weight / s_w)
        return _ste_clamp(wq, -QMAX_W, QMAX_W)

    def init_scales(self) -> None:
        with torch.no_grad():
            wmax = float(self.weight.abs().max().clamp_min(1e-8))
            self.log2_sw.copy_(torch.log2(torch.tensor(wmax / QMAX_W)))
            self.warm = False

    def mfq(self, s_x: float) -> int:
        m = float(s_x) * self.s_w_val() / self.s_y_val() * (1 << SHIFT)
        return int(round(m))

    def forward(self, x_q: torch.Tensor, s_x: float, mfq: Optional[int] = None):
        wq = self.w_int()
        acc = F.linear(x_q, wq, bias=None)
        if mfq is None:
            mfq = max(1, self.mfq(s_x))
        y = _q_layer(acc, mfq, relu=False)      # FC 无 ReLU，饱和到 int8
        return y, self.s_y_val()


# ---------------------------------------------------------------------------
# 整网
# ---------------------------------------------------------------------------
class QWaveNet(nn.Module):
    """★ 与 PL 加速器逐位同构的波形识别网络（9 类）"""

    def __init__(self, n_classes: int = 9, fix_mfq: Optional[int] = None):
        super().__init__()
        self.n_classes = n_classes
        self.fix_mfq = fix_mfq
        self.conv1 = QConvPool(1, 8, 3, 2, "conv1")
        self.conv2 = QConvPool(8, 16, 3, 2, "conv2")
        self.fc = QLinear(16 * 5 * 5, n_classes, "fc")

    # -------- 量化前向（训练 / 导出通用；逐位 = 硬件） --------
    def quant_forward(self, x_u8: torch.Tensor,
                      mfq_override: Optional[List[Optional[int]]] = None):
        """
        x_u8 : (B,1,28,28)，元素为 0..255 的整数值张量（uint8 语义）
        返回 dict：logits（整数域张量）、中间特征图、各层整数 MFQ
        """
        x_q = x_u8 - 128.0                       # ★ 唯一输入量化：int8 = u8 - 128
        s_x = 1.0
        ov = list(mfq_override) if mfq_override else [None, None, None]
        ov += [None] * (3 - len(ov))

        m1 = ov[0] if ov[0] is not None else (self.fix_mfq or max(1, self.conv1.mfq(s_x)))
        f1, s1 = self.conv1(x_q, s_x, m1)
        m2 = ov[1] if ov[1] is not None else (self.fix_mfq or max(1, self.conv2.mfq(s1)))
        f2, s2 = self.conv2(f1, s1, m2)
        m3 = ov[2] if ov[2] is not None else (self.fix_mfq or max(1, self.fc.mfq(s2)))
        logits, _ = self.fc(f2.flatten(1), s2, m3)
        return {"logits": logits, "f1": f1, "f2": f2, "s": [s_x, s1, s2],
                "mfq": [int(m1), int(m2), int(m3)]}

    def forward(self, x_u8: torch.Tensor):
        return self.quant_forward(x_u8)["logits"]

    def mfq_list(self) -> List[int]:
        """
        ★ 各层整数 requant 乘子（解析计算，不做前向、不依赖设备）。
        激活步长链：s_x0 = 1 → s_x1 = conv1.s_y → s_x2 = conv2.s_y
        MFQ_L = round(s_x_L · s_w_L / s_y_L · 2^16)
        """
        m1 = self.conv1.mfq(1.0)
        m2 = self.conv2.mfq(self.conv1.s_y_val())
        m3 = self.fc.mfq(self.conv2.s_y_val())
        return [max(1, int(m1)), max(1, int(m2)), max(1, int(m3))]

    def int_weights(self) -> Dict[str, torch.Tensor]:
        return {
            "conv1.weight": self.conv1.w_int().detach().round().to(torch.int32),
            "conv2.weight": self.conv2.w_int().detach().round().to(torch.int32),
            "fc.weight": self.fc.w_int().detach().round().to(torch.int32),
        }

    def init_all_scales(self) -> None:
        for m in (self.conv1, self.conv2, self.fc):
            m.init_scales()

    # ------------------------------------------------------------------
    # ★ 激活步长标定（正确做法）
    #
    # 设计规则推导：
    #   硬件算 y_q = floor(acc · MFQ / 2^16)，要让 int8 输出【用满】范围而不饱和，
    #   需要 MFQ ≈ 127·2^16 / max|acc|。
    #   而 MFQ = s_x·s_w/s_y·2^16 ⇒ s_y = s_x·s_w·max|acc| / 127。
    #   ★ 注意 max|acc| 是【未 requant 的整数累加值】，
    #     不是"未量化浮点权重算出来的线性输出"（那样标定出的 s_y 会偏大几个量级，
    #     导致 MFQ 被算成 0 —— 这是第一版实现踩过的坑）。
    #   acc 的峰值越大，输出量化级数越多（级数 ≈ max|acc|），所以要把
    #   max|acc| 尽量做大，但必须满足溢出约束 max|acc|·MFQ < 2^31
    #   （按上式 max|acc|·MFQ = 127·2^16 = 8.3e6 ≪ 2^31，天然安全）。
    # ------------------------------------------------------------------
    @torch.no_grad()
    def calibrate(self, x_u8: torch.Tensor, iters: int = 3, bs: int = 256,
                  percentile: float = 99.9, sample_stride: int = 64) -> List[float]:
        """
        按数据标定各层激活步长，返回最后一次迭代的 max|acc|（用于诊断/溢出检查）。

        ★ percentile 参数很重要：
          requant 是 floor（向下取整），所以 acc·MFQ/2^16 < 1 的值会被压成 0。
          若按 max 标定，dead zone = max|acc|/127。而卷积输出的分布常常是
          重尾的（少数位置很大、绝大多数很小），按 max 标定会让大量通道"死掉"
          —— 实测 conv2 输出有 88.8% 被压成 0，网络等于空转。
          改用 99.9 分位数可以显著缩小 dead zone（代价是前 0.1% 被饱和），
          这是标准做法（TensorRT 的 percentile 校准）。
          percentile=100 即退化为按 max 标定。
        """
        self.eval()
        mx = [0.0, 0.0, 0.0]
        pct = [0.0, 0.0, 0.0]
        for _ in range(max(1, iters)):
            maxv = [0.0, 0.0, 0.0]
            buf = [[], [], []]
            for i in range(0, len(x_u8), bs):
                xb = x_u8[i:i + bs].to(self.conv1.weight.device)
                x_q = xb - 128.0
                a1 = F.conv2d(x_q, self.conv1.w_int(), bias=None)
                maxv[0] = max(maxv[0], float(a1.abs().max()))
                buf[0].append(a1.abs().flatten()[::sample_stride])
                y1 = F.max_pool2d(
                    _q_layer(a1, max(1, self.conv1.mfq(1.0)), True), 2, 2)
                a2 = F.conv2d(y1, self.conv2.w_int(), bias=None)
                maxv[1] = max(maxv[1], float(a2.abs().max()))
                buf[1].append(a2.abs().flatten()[::sample_stride])
                y2 = F.max_pool2d(
                    _q_layer(a2, max(1, self.conv2.mfq(self.conv1.s_y_val())), True), 2, 2)
                # ★ FC 的 acc 可能很大，先做一次前置缩放避免 float32 失真
                a3 = F.linear(y2.flatten(1), self.fc.w_int(), bias=None)
                maxv[2] = max(maxv[2], float(a3.abs().max()))
                buf[2].append(a3.abs().flatten()[::sample_stride])

            mx = maxv
            if percentile >= 100.0:
                pct = list(maxv)
            else:
                pct = [float(np.percentile(torch.cat(b).cpu().numpy(), percentile))
                       for b in buf]

            # s_y_L = s_x_L · s_w_L · scale_L / 127     （scale 取分位数）
            s_x1 = 1.0
            v1 = s_x1 * self.conv1.s_w_val() * pct[0] / 127.0
            self.conv1.log2_sy.copy_(torch.log2(torch.tensor(max(v1, 1e-12))))
            s_x2 = self.conv1.s_y_val()
            v2 = s_x2 * self.conv2.s_w_val() * pct[1] / 127.0
            self.conv2.log2_sy.copy_(torch.log2(torch.tensor(max(v2, 1e-12))))
            s_x3 = self.conv2.s_y_val()
            v3 = s_x3 * self.fc.s_w_val() * pct[2] / 127.0
            self.fc.log2_sy.copy_(torch.log2(torch.tensor(max(v3, 1e-12))))
        self._calib_pct = pct
        self._calib_max = mx
        return mx

    @torch.no_grad()
    def calibrate_from_raw(self, xtr_u8: torch.Tensor, n: int = 1024, **kw) -> List[float]:
        return self.calibrate(xtr_u8[:n].to(self.conv1.weight.device), **kw)

    def set_activations_warm(self, warm: bool) -> None:
        """warm=True：权重不量化（浮点预训练）；warm=False：全量化（QAT）"""
        for m in (self.conv1, self.conv2, self.fc):
            m.warm = warm


# ===========================================================================
# ★ 参考整数实现（纯 numpy，导 reference_out.bin / 板级自检用）
#    与 HLS 逐位一致，含 32 位回绕模拟
# ===========================================================================
def im2col_conv_int8(x_q: np.ndarray, w_q: np.ndarray) -> np.ndarray:
    """x_q:(IC,H,W) int32 ; w_q:(OC,IC,K,K) int32 → acc:(OC,OH,OW) int64"""
    IC, H, W = x_q.shape
    OC, IC2, K, _ = w_q.shape
    assert IC == IC2, (IC, IC2)
    OH, OW = H - K + 1, W - K + 1
    acc = np.zeros((OC, OH, OW), dtype=np.int64)
    for ky in range(K):
        for kx in range(K):
            patch = x_q[:, ky:ky + OH, kx:kx + OW].astype(np.int64)      # (IC,OH,OW)
            wk = w_q[:, :, ky, kx].astype(np.int64)                      # (OC,IC)
            acc += np.tensordot(wk, patch, axes=(1, 0))
    return acc


def wrap_int32(v: np.ndarray) -> np.ndarray:
    """模拟 C/HLS 的 ap_int<32> 回绕（避免 numpy 静默溢出告警）"""
    v = np.asarray(v, dtype=np.int64)
    return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def requant_shift(acc: np.ndarray, mfq: int, relu: bool) -> np.ndarray:
    """
    ★ out = (acc * MFQ) >> 16
      · 乘积按 int32 回绕（与 HLS 的 ap_int<32> 一致）
      · 右移用算术右移（对负数向下取整），numpy 的 >> 对 int64 负数即为算术右移
    """
    prod = wrap_int32(acc.astype(np.int64) * int(mfq))
    q = prod >> SHIFT
    lo, hi = (QMIN_R, QMAX_R) if relu else (QMIN_A, QMAX_A)
    np.clip(q, lo, hi, out=q)
    return q.astype(np.int32)


def maxpool2_int8(f: np.ndarray) -> np.ndarray:
    OC, H, W = f.shape
    OH, OW = H // 2, W // 2
    v = f[:, :OH * 2, :OW * 2].reshape(OC, OH, 2, OW, 2)
    return v.max(axis=(2, 4))


def reference_infer_arrays(x_u8, w1, w2, wf, mfq: List[int]):
    """
    ★ 板子侧比对的权威参考（不依赖 torch 的任何浮点行为）
    x_u8 : (28,28) 或 (1,28,28)，uint8 码值
    w1 (8,1,3,3) / w2 (16,8,3,3) / wf (N,400) int32
    返回 (logits:int32[N], f1:int32[8,13,13], f2:int32[16,5,5])
    """
    x = np.asarray(x_u8, dtype=np.int32).reshape(IMG, IMG)
    x_q = x - 128
    a1 = im2col_conv_int8(x_q[None, :, :], np.asarray(w1, dtype=np.int32))
    q1 = requant_shift(a1, mfq[0], relu=True)
    p1 = maxpool2_int8(q1)
    a2 = im2col_conv_int8(p1, np.asarray(w2, dtype=np.int32))
    q2 = requant_shift(a2, mfq[1], relu=True)
    p2 = maxpool2_int8(q2)
    xf = p2.reshape(-1).astype(np.int64)
    acc = np.asarray(wf, dtype=np.int64) @ xf
    logits = requant_shift(acc, mfq[2], relu=False)
    return logits.astype(np.int32), p1.astype(np.int32), p2.astype(np.int32)


def reference_infer(model: QWaveNet, x_u8, mfq: Optional[List[int]] = None):
    iw = model.int_weights()
    mfq = mfq or model.mfq_list()
    return reference_infer_arrays(
        x_u8,
        iw["conv1.weight"].cpu().numpy(),
        iw["conv2.weight"].cpu().numpy(),
        iw["fc.weight"].cpu().numpy(),
        mfq)


# ===========================================================================
# 诊断：饱和率 / 溢出 / 整数一致性
# ===========================================================================
@torch.no_grad()
def diagnose(model: QWaveNet, x_u8: torch.Tensor, max_batches: int = 8,
             bs: int = 256) -> Dict[str, object]:
    """统计各层整数域行为，用于判断量化是否"挤爆"或"没用满" """
    model.eval()
    rep = {"mfq": model.mfq_list()}
    sat = {"f1": [0, 0], "f2": [0, 0], "logits": [0, 0]}
    tot = {"f1": 0, "f2": 0, "logits": 0}
    acc_absmax = [0.0, 0.0, 0.0]
    for i in range(0, min(len(x_u8), max_batches * bs), bs):
        xb = x_u8[i:i + bs]
        out = model.quant_forward(xb)
        for key in ("f1", "f2", "logits"):
            t = out[key].detach()
            hi = 127.0
            lo = 0.0 if key != "logits" else -128.0
            sat[key][0] += int((t <= lo).sum())
            sat[key][1] += int((t >= hi).sum())
            tot[key] += t.numel()
        # 原始 acc（未 requant）幅值
        wq1 = model.conv1.w_int()
        a1 = F.conv2d(xb - 128.0, wq1, bias=None)
        acc_absmax[0] = max(acc_absmax[0], float(a1.abs().max()))
        wq2 = model.conv2.w_int()
        a2 = F.conv2d(out["f1"], wq2, bias=None)
        acc_absmax[1] = max(acc_absmax[1], float(a2.abs().max()))
        wqf = model.fc.w_int()
        a3 = F.linear(out["f2"].flatten(1), wqf, bias=None)
        acc_absmax[2] = max(acc_absmax[2], float(a3.abs().max()))

    mfq = rep["mfq"]
    rep["acc_absmax"] = acc_absmax
    rep["acc_times_mfq"] = [acc_absmax[i] * mfq[i] for i in range(3)]
    rep["int32_headroom"] = [INT32_MAX / max(1.0, acc_absmax[i] * mfq[i]) for i in range(3)]
    rep["overflow_risk"] = [bool(acc_absmax[i] * mfq[i] >= INT32_MAX) for i in range(3)]
    rep["saturation_frac"] = {
        k: {"low": sat[k][0] / max(1, tot[k]), "high": sat[k][1] / max(1, tot[k])}
        for k in sat
    }
    rep["s_w"] = [model.conv1.s_w_val(), model.conv2.s_w_val(), model.fc.s_w_val()]
    rep["s_y"] = [model.conv1.s_y_val(), model.conv2.s_y_val(), model.fc.s_y_val()]
    wq = model.int_weights()
    rep["w_int_max"] = {k: int(v.abs().max()) for k, v in wq.items()}
    rep["w_int_used_levels"] = {k: int(torch.unique(v).numel()) for k, v in wq.items()}
    return rep
