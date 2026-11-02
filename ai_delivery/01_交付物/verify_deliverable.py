#!/usr/bin/env python3
"""
verify_deliverable.py —— ★ 交付包自检（只依赖 numpy，不需要 torch / 本项目其它代码）

用途：
  · 主线融合负责人拿到 `quantized_model/` 后**先跑这个**，确认交付包本身自洽；
  · 上板后用**同样的判据**比对硬件输出（就是上一轮 `[CNN OK] N/N 点一致` 那套）。

它做三件事：
  1. 按 `model_spec.json` 的 `weights_layout` 从 `weights.bin` 读出各层 int8 权重；
  2. 用**与 HLS 循环逐位一致**的纯整数复刻（含 `ap_int<32>` 溢出回绕）跑 `reference_in.bin`；
  3. 与 `reference_out.bin` 逐点比对 —— 必须 100% 相同。

覆盖两种拓扑：
  · CNN（波形识别）：conv 走 ReLU+sat[0,127]，conv 与 2×2 maxpool 融合；fc 走 sat[-128,127]
  · MLP（RL 策略）  ：全部层 sat[-128,127]（对应浮点的 HardTanh）；末尾若干 head 共享同一输入

用法：
    python verify_deliverable.py                 # 自动扫描同目录下的交付目录
    python verify_deliverable.py <目录> [<目录> ...]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

SHIFT = 16


# ---------------------------------------------------------------------------
# 整数算子（与 HLS 逐位一致）
# ---------------------------------------------------------------------------
def wrap32(v):
    """模拟 ap_int<32> 回绕（`acc*MFQ` 在 HLS 里就是 32 位乘）"""
    v = np.asarray(v, dtype=np.int64)
    return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def requant(acc, mfq, relu):
    """★ out = (acc * MFQ) >> 16 ；算术右移 = floor；relu=True 时饱和到 [0,127]"""
    prod = wrap32(np.asarray(acc, dtype=np.int64) * int(mfq))
    q = prod >> SHIFT                      # int64 的 >> 对负数就是算术右移
    np.clip(q, 0 if relu else -128, 127, out=q)
    return q


def conv_int8(x, w):
    """x:(IC,H,W) int ; w:(OC,IC,K,K) int → acc:(OC,OH,OW)，索引顺序与 HLS 一致"""
    IC, H, W = x.shape
    OC, IC2, K, _ = w.shape
    assert IC == IC2, "通道不匹配 %s vs %s" % ((IC, H, W), w.shape)
    OH, OW = H - K + 1, W - K + 1
    acc = np.zeros((OC, OH, OW), dtype=np.int64)
    for ky in range(K):
        for kx in range(K):
            patch = x[:, ky:ky + OH, kx:kx + OW].astype(np.int64)   # (IC,OH,OW)
            wk = w[:, :, ky, kx].astype(np.int64)                   # (OC,IC)
            acc += np.tensordot(wk, patch, axes=(1, 0))
    return acc


def maxpool2(f):
    OC, H, W = f.shape
    OH, OW = H // 2, W // 2
    return f[:, :OH * 2, :OW * 2].reshape(OC, OH, 2, OW, 2).max(axis=(2, 4))


# ---------------------------------------------------------------------------
# 两种拓扑的前向
# ---------------------------------------------------------------------------
def infer_cnn(blobs, x, mfq):
    a = requant(conv_int8(x[None] if x.ndim == 2 else x, blobs[0]), mfq[0], True)
    a = maxpool2(a)
    b = requant(conv_int8(a, blobs[1]), mfq[1], True)
    b = maxpool2(b)
    return requant(blobs[2].astype(np.int64) @ b.reshape(-1).astype(np.int64),
                   mfq[2], False)


def infer_mlp(layers, blobs, x, mfq):
    """前 n_body 个是隐层（顺序前向），其余是动作头（共享隐层输出）"""
    is_head = [bool(l.get("head") or str(l.get("name", "")).startswith("head"))
               for l in layers]
    n_body = is_head.index(True) if any(is_head) else len(layers)
    h = x.reshape(-1).astype(np.int64)
    for k in range(n_body):
        h = requant(blobs[k].astype(np.int64) @ h, mfq[k], False)   # 全部 sat[-128,127]
    outs = [requant(blobs[k].astype(np.int64) @ h, mfq[k], False)
            for k in range(n_body, len(layers))]
    return np.concatenate(outs) if outs else h


# ---------------------------------------------------------------------------
def load_weights(bin_path, entries):
    raw = np.fromfile(bin_path, dtype=np.uint8).astype(np.int8)
    blobs = []
    for e in entries:
        n = int(e["bytes"]) if e.get("bytes") else int(np.prod(e["shape"]))
        seg = raw[e["offset"]:e["offset"] + n]
        assert len(seg) == n, "权重越界：%s" % e
        blobs.append(seg.reshape(e["shape"]) if e.get("shape") else seg)
    return blobs


def mfq_list(spec):
    m = spec["requant"].get("MFQ_per_layer")
    if isinstance(m, (list, tuple)):
        return [int(v) for v in m]
    if isinstance(m, dict):
        return [int(v) for v in m.values()]          # dict 保持写入顺序 fc0→…→head…
    return [int(spec["requant"]["MFQ"])] * 64


def verify_dir(d):
    mp = os.path.join(d, "model_spec.json")
    if not os.path.exists(mp):
        return None
    spec = json.load(open(mp, encoding="utf-8"))
    blobs = load_weights(os.path.join(d, "weights.bin"),
                         spec["weights_layout"]["entries"])
    mfq = mfq_list(spec)
    layers = spec["layers"]
    is_cnn = any(l.get("type") == "conv" for l in layers)

    in_shape = spec["input_shape"]
    in_bytes = int(np.prod(in_shape))
    hh, ww = (in_shape[-2], in_shape[-1]) if len(in_shape) >= 2 else (in_shape[0], 1)
    if is_cnn:
        n_out = int([l for l in layers if l.get("type") == "fc"][-1]["out"])
    else:
        heads = [l for l in layers
                 if l.get("head") or str(l.get("name", "")).startswith("head")]
        n_out = sum(int(l["out"]) for l in heads) if heads else int(layers[-1]["out"])

    rin = np.fromfile(os.path.join(d, "reference_in.bin"), dtype=np.int8)
    rout = np.fromfile(os.path.join(d, "reference_out.bin"), dtype=np.int8)
    assert len(rin) % in_bytes == 0, "reference_in.bin 长度不是输入尺寸整数倍"
    N = len(rin) // in_bytes
    assert len(rout) == N * n_out, \
        "reference_out.bin 长度 %d != %d 组 × %d 输出" % (len(rout), N, n_out)

    ok, bad = 0, []
    for k in range(N):
        x = rin[k * in_bytes:(k + 1) * in_bytes].reshape(hh, ww) if ww > 1 \
            else rin[k * in_bytes:(k + 1) * in_bytes]
        lg = infer_cnn(blobs, x, mfq) if is_cnn else infer_mlp(layers, blobs, x.reshape(-1), mfq)
        exp = rout[k * n_out:(k + 1) * n_out]
        same = int((lg.astype(np.int8) == exp).sum())
        ok += same
        if same != n_out:
            bad.append(k)
    tot = N * n_out
    print("  %-32s %2d 组 × %2d 点 → %4d/%4d %s"
          % (os.path.basename(os.path.normpath(d)), N, n_out, ok, tot,
             "✅ OK" if ok == tot else "❌ MISMATCH @ %s" % bad[:5]))
    if len(mfq) >= 3:
        print("       MFQ = %s" % (mfq[:5] if len(mfq) > 3 else mfq))
    return ok == tot


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    dirs = sys.argv[1:]
    if not dirs:
        dirs = [os.path.join(base, n) for n in sorted(os.listdir(base))
                if os.path.isdir(os.path.join(base, n))
                and os.path.exists(os.path.join(base, n, "model_spec.json"))]
    print("=" * 74)
    print(" 交付包自检： weights.bin + reference_in.bin  →  与 reference_out.bin 逐点比对")
    print(" 用的是 HLS 循环的纯整数复刻（含 ap_int<32> 溢出回绕模拟）")
    print("=" * 74)
    allok = True
    for d in dirs:
        r = verify_dir(d)
        if r is not None:
            allok &= r
    print()
    print("★ 全部通过" if allok else "★ 存在不一致，请检查")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
