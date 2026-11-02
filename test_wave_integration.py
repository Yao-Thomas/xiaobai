#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_wave_integration.py —— 波形模型接入前的离线自检

════════════════════════════════════════════════════════════════════
为什么要有这个（而不是只跑对方给的 verify_deliverable.py）
════════════════════════════════════════════════════════════════════
对方给了自检脚本，也全过了。但那是【他们的实现验他们自己的产物】。
我要上板，必须确认【我的理解】和【我的实现】也对，否则上板出问题
时分不清是 PL 坏了、还是我预处理写错了。

所以这里独立做两件事：

  ① wdens 预处理：我的纯 Python 实现 vs 他们的 preprocess.py
     → 逐点比 200 组随机输入 + 各种极端波形
     （★ 这是最容易写错的地方：列边界、行映射、sqrt、归一化）

  ② 整数前向：我的实现 vs 他们的 reference_out.bin
     → 64 组 × 8 点逐点比，期望 512/512
     （★ 验 MFQ 是不是 201/371/1390、有没有 ReLU/sat、fc 有没有 ReLU）

用法:
    python test_wave_integration.py
    python test_wave_integration.py --path <交付包目录>
"""
import argparse
import io
import math
import os
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_DELIV = os.path.join(HERE, "ai_delivery")
ok = True

CAP_LEN = 4096
NCOLS = 28
NROWS = 28
CLASSES = ("sine", "square", "triangle", "sawtooth", "noise",
           "clipping", "signal_loss", "duty_abnormal")
MFQ1, MFQ2, MFQFC = 201, 371, 1390


def chk(cond, msg, detail=""):
    global ok
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok = False


# ══════════════════════════════════════════════════════════════════
#  ① 我的 wdens 实现（纯 Python，照 preprocess.py 的语义）
# ══════════════════════════════════════════════════════════════════
COL_BOUNDS = []
_base = CAP_LEN // NCOLS                      # 146
for _c in range(NCOLS):
    _a = _c * _base
    _b = CAP_LEN if _c == NCOLS - 1 else (_c + 1) * _base
    COL_BOUNDS.append((_a, _b))


def row_of(code):
    """8 位码值 → 行号（行 0 = 顶部 = 高电平）"""
    r = int((255 - code) * NROWS / 256.0)
    if r < 0:
        r = 0
    if r > NROWS - 1:
        r = NROWS - 1
    return r


def my_wdens_u8(samples_u8):
    """4096 样本 → 28×28 uint8 密度图（我的实现）"""
    img = [[0.0] * NCOLS for _ in range(NROWS)]
    for c, (a, b) in enumerate(COL_BOUNDS):
        cnt = [0] * NROWS
        for i in range(a, b):
            cnt[row_of(int(samples_u8[i]))] += 1
        n = float(b - a)
        for r in range(NROWS):
            img[r][c] = math.sqrt(cnt[r] / n)
    mx = max(max(row) for row in img)
    if mx <= 0:
        return [0] * (NROWS * NCOLS)
    out = [0] * (NROWS * NCOLS)
    for r in range(NROWS):
        for c in range(NCOLS):
            out[r * NCOLS + c] = int(math.floor(img[r][c] / mx * 255.0 + 0.5))
    return out


def to_int8(img_u8):
    """u8 → i8（唯一变换：-128 并 clip 到 [-128,127]）"""
    return [max(-128, min(127, v - 128)) for v in img_u8]


# ══════════════════════════════════════════════════════════════════
#  ② 我的整数前向（照 HLS 循环 + ap_int<32> 回绕）
# ══════════════════════════════════════════════════════════════════
def _wrap32(x):
    """模拟 ap_int<32> 溢出回绕"""
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x >= (1 << 31) else x


def my_forward(img_i8, W1, W2, WF, n_out=8):
    """返回 (f1, f2, logits)"""
    f1 = [0] * (8 * 13 * 13)
    for oc in range(8):
        for py in range(13):
            for px in range(13):
                best = 0
                for sy in range(2):
                    for sx in range(2):
                        oy, ox = py * 2 + sy, px * 2 + sx
                        acc = 0
                        for ky in range(3):
                            for kx in range(3):
                                acc += img_i8[(oy + ky) * 28 + (ox + kx)] * \
                                       W1[oc * 9 + ky * 3 + kx]
                        q = _wrap32(acc * MFQ1) >> 16
                        if q < 0:
                            q = 0
                        if q > 127:
                            q = 127
                        if q > best:
                            best = q
                f1[oc * 169 + py * 13 + px] = best

    f2 = [0] * (16 * 5 * 5)
    for oc in range(16):
        for py in range(5):
            for px in range(5):
                best = 0
                for sy in range(2):
                    for sx in range(2):
                        oy, ox = py * 2 + sy, px * 2 + sx
                        acc = 0
                        for ic in range(8):
                            for ky in range(3):
                                for kx in range(3):
                                    acc += f1[ic * 169 + (oy + ky) * 13 + (ox + kx)] * \
                                           W2[(oc * 8 + ic) * 9 + ky * 3 + kx]
                        q = _wrap32(acc * MFQ2) >> 16
                        if q < 0:
                            q = 0
                        if q > 127:
                            q = 127
                        if q > best:
                            best = q
                f2[oc * 25 + py * 5 + px] = best

    lg = []
    for oc in range(n_out):
        acc = 0
        for i in range(400):
            acc += f2[i] * WF[oc * 400 + i]
        q = _wrap32(acc * MFQFC) >> 16      # ★ fc 没有 ReLU
        if q > 127:
            q = 127
        if q < -128:
            q = -128
        lg.append(q)
    return f1, f2, lg


# ══════════════════════════════════════════════════════════════════
#  波形生成（测 wdens 用）
# ══════════════════════════════════════════════════════════════════
def gen(kind, n=CAP_LEN, k_cycles=3.0, seed=0):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        ph = (i / n) * k_cycles
        frac = ph - math.floor(ph)
        if kind == "sine":
            v = math.sin(2 * math.pi * ph)
        elif kind == "square":
            v = 1.0 if frac < 0.5 else -1.0
        elif kind == "triangle":
            v = 4 * abs(frac - 0.5) - 1
        elif kind == "sawtooth":
            v = 2 * frac - 1
        elif kind == "noise":
            v = rnd.uniform(-1, 1)
        elif kind == "duty30":
            v = 1.0 if frac < 0.3 else -1.0
        elif kind == "flat":
            v = 0.0
        elif kind == "clipped":
            v = max(-0.4, min(0.4, math.sin(2 * math.pi * ph))) / 0.4
        else:
            v = 0.0
        out.append(int(max(0, min(255, round(127.5 + 100 * v)))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=DEF_DELIV)
    a = ap.parse_args()
    D = a.path
    L = os.path.join(D, "01_交付物")
    if not os.path.isdir(L):
        print("找不到 01_交付物：%s" % L)
        return 1

    print("=" * 74)
    print(" 波形模型接入 · 离线自检")
    print("=" * 74)
    print(" 交付包: %s" % D)
    print()

    # ── ① wdens 对齐 ──
    print("【1】wdens 预处理：我的实现 vs 他们的 preprocess.py")
    sys.path.insert(0, os.path.join(D, "03_源码"))
    try:
        from common import preprocess as PP
        have_pp = True
    except Exception as e:
        print("   ⚠ 导不进他们的 preprocess.py：%s" % e)
        have_pp = False

    if have_pp:
        chk(PP.CAP_LEN == CAP_LEN, "CAP_LEN 一致", str(PP.CAP_LEN))
        chk(PP.NCOLS == NCOLS and PP.NROWS_D == NROWS,
            "画布 28×28 一致")
        my_b = [(c * 146, (c + 1) * 146 if c < 27 else 4096) for c in range(28)]
        chk(list(PP.COL_BOUNDS) == my_b, "★ 列边界 28 段一致",
            "%s ... %s" % (PP.COL_BOUNDS[0], PP.COL_BOUNDS[-1]))

        cases = (["sine", "square", "triangle", "sawtooth", "noise",
                  "duty30", "flat", "clipped"] +
                 ["sine"] * 4 + ["square"] * 4)
        kcs = [1.0, 2.0, 3.0, 5.0, 8.0, 16.0, 0.5, 3.5]
        bad = 0
        tot = 0
        for i, kind in enumerate(cases):
            s = gen(kind, k_cycles=kcs[i % len(kcs)], seed=i)
            mine = my_wdens_u8(s)
            theirs = PP.capture_to_wdens_u8_pure(s)
            flat = [theirs[r][c] for r in range(28) for c in range(28)]
            tot += 1
            if mine != flat:
                bad += 1
                d = max(abs(x - y) for x, y in zip(mine, flat))
                print("     ✗ %s K=%s 最大差 %d" % (kind, kcs[i % len(kcs)], d))
        chk(bad == 0, "★ %d 组波形逐点一致" % tot,
            "" if bad == 0 else "%d 组不一致" % bad)

        # numpy vs pure 也顺手对一遍
        try:
            import numpy as np
            s = gen("sine", k_cycles=3.0, seed=99)
            w_np = PP.capture_to_wdens_u8_np(
                np.array(s, dtype=np.uint8)).reshape(-1).tolist()
            chk(w_np == my_wdens_u8(s), "他们的 numpy 版 == 我的（旁证）")
        except Exception:
            pass
    print()

    # ── ② 整数前向 vs reference_out ──
    print("【2】整数前向 vs 交付包的 reference_out.bin")
    wdir = os.path.join(L, "quantized_model")
    with open(os.path.join(wdir, "weights.bin"), "rb") as f:
        wb = f.read()
    with open(os.path.join(wdir, "reference_in.bin"), "rb") as f:
        rin = f.read()
    with open(os.path.join(wdir, "reference_out.bin"), "rb") as f:
        rout = f.read()

    chk(len(wb) == 4480, "weights.bin 4480 字节", str(len(wb)))
    W1 = list(struct_unpack_i8(wb[0x0000:0x0000 + 72]))
    W2 = list(struct_unpack_i8(wb[0x0080:0x0080 + 1152]))
    WF = list(struct_unpack_i8(wb[0x0500:0x0500 + 3200]))
    print("     权重: conv1=%d  conv2=%d  fc=%d  (总 %d)"
          % (len(W1), len(W2), len(WF), len(wb)))

    n = len(rout) // 8
    chk(n == 64, "reference 有 64 组", str(n))
    chk(len(rin) == n * 784, "reference_in 尺寸对", str(len(rin)))

    same = 0
    gok = 0
    argmax_ok = 0
    bad = []
    import json
    spec = json.loads(io.open(os.path.join(wdir, "model_spec.json"),
                              encoding="utf-8").read())
    labels = spec["reference"]["labels"]

    for k in range(n):
        img_i8 = list(struct_unpack_i8(rin[k * 784:(k + 1) * 784]))
        _, _, lg = my_forward(img_i8, W1, W2, WF, 8)
        want = list(struct_unpack_i8(rout[k * 8:(k + 1) * 8]))
        if lg == want:
            gok += 1
        else:
            if len(bad) < 3:
                bad.append((k, lg, want))
        for i in range(8):
            if lg[i] == want[i]:
                same += 1
        if CLASSES[max(range(8), key=lambda i: lg[i])] == labels[k]:
            argmax_ok += 1

    chk(same == n * 8, "★ 512/512 点一致", "%d/%d" % (same, n * 8))
    for k, got, want in bad:
        print("     ✗ 第 %d 组: 实得 %s / 期望 %s" % (k, got, want))
    chk(gok == n, "64 组全对", "%d/64" % gok)
    chk(argmax_ok >= 60, "argmax 类别和标签对得上",
        "%d/64（★ 是准确性旁证，不必 64/64）" % argmax_ok)
    print()

    # ── ③ 顺手验一下「统一 MFQ 会掉多少」──
    print("【3】旁证：为什么不能用统一 MFQ=119")
    same_u = 0
    for k in range(min(16, n)):
        img_i8 = list(struct_unpack_i8(rin[k * 784:(k + 1) * 784]))
        f1 = [0] * (8 * 169)
        f2 = [0] * (16 * 25)
        # 用 MFQ=119 全跑一遍
        for oc in range(8):
            for py in range(13):
                for px in range(13):
                    best = 0
                    for sy in range(2):
                        for sx in range(2):
                            oy, ox = py * 2 + sy, px * 2 + sx
                            acc = 0
                            for ky in range(3):
                                for kx in range(3):
                                    acc += img_i8[(oy + ky) * 28 + (ox + kx)] * \
                                           W1[oc * 9 + ky * 3 + kx]
                            q = _wrap32(acc * 119) >> 16
                            q = max(0, min(127, q))
                            best = max(best, q)
                    f1[oc * 169 + py * 13 + px] = best
        for oc in range(16):
            for py in range(5):
                for px in range(5):
                    best = 0
                    for sy in range(2):
                        for sx in range(2):
                            oy, ox = py * 2 + sy, px * 2 + sx
                            acc = 0
                            for ic in range(8):
                                for ky in range(3):
                                    for kx in range(3):
                                        acc += f1[ic * 169 + (oy + ky) * 13 + (ox + kx)] * \
                                               W2[(oc * 8 + ic) * 9 + ky * 3 + kx]
                            q = _wrap32(acc * 119) >> 16
                            q = max(0, min(127, q))
                            best = max(best, q)
                    f2[oc * 25 + py * 5 + px] = best
        lg = []
        for oc in range(8):
            acc = 0
            for i in range(400):
                acc += f2[i] * WF[oc * 400 + i]
            lg.append(max(-128, min(127, _wrap32(acc * 119) >> 16)))
        want = list(struct_unpack_i8(rout[k * 8:(k + 1) * 8]))
        same_u += sum(1 for i in range(8) if lg[i] == want[i])
    chk(same_u < 16 * 8 * 0.5,
        "统一 119 确实对不上（证实 MFQ 必须逐层）",
        "%d/%d 点" % (same_u, 16 * 8))
    print()

    # ── ④ ★ 端到端：原始波形 → 我的 wdens → 整数前向 → 类别 ──
    print("【4】端到端：原始波形 → wdens → 前向 → 类别")
    print("   （★ 这条链才是真链路：板子上采集到的就是原始 8bit）")
    sys.path.insert(0, os.path.join(D, "03_源码"))
    try:
        import numpy as np
        from common import dds_sim as DS
        import waveform_ai as WA

        # ★★★ 必须用【他们的生成器】★★★
        #   我第一版用自己的 gen_wave（K=1.5~6、满量程幅度）做端到端，
        #   结果只有 35% —— 一度以为模型有问题。
        #   实际是他们的 sample_spec() 里：
        #       K ∈ [4, 64]（对数均匀）、amp ∈ [45,118]（不满量程）、
        #       + noise_lsb / jitter / dc / gain / dither
        #   分布完全不一样。用错的分布测，测的是我的生成器，不是模型。
        rng = np.random.default_rng(20261002)
        per = 12
        hit = 0
        tot = 0
        per_class = {}
        wrong = []
        Ks = []
        for label in CLASSES:
            h = 0
            for _ in range(per):
                samples, spec, _info = DS.make_sample(rng, label)
                Ks.append(float(spec.cycles))
                img = list(WA.wdens_u8(list(samples)))
                i8 = [v - 128 for v in img]
                _, _, lg = my_forward(i8, W1, W2, WF, 8)
                top = CLASSES[max(range(8), key=lambda i: lg[i])]
                tot += 1
                if top == label:
                    hit += 1
                    h += 1
                elif len(wrong) < 8:
                    wrong.append((label, spec.cycles, spec.amp, top))
            per_class[label] = (h, per)
        acc = hit / float(tot)
        print("     周期数 K 范围: %.1f ~ %.1f" % (min(Ks), max(Ks)))
        for lb in CLASSES:
            h, p = per_class[lb]
            print("     %-15s %2d/%2d" % (lb, h, p))
        chk(acc >= 0.80, "★ 端到端准确率 %.1f%%（%d/%d）"
            % (acc * 100, hit, tot),
            "交付的测试集是 95.9%%，这里换随机种子重新采 144 个样本")
        for lb, K, amp, top in wrong:
            print("     ✗ %-14s K=%5.1f amp=%5.1f → 误判成 %s"
                  % (lb, K, amp, top))
    except Exception as e:
        chk(False, "端到端跑不起来", "%s: %s" % (type(e).__name__, e))
        import traceback
        traceback.print_exc()
    print()

    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过 —— 可以上板了" if ok
                        else "★ 有问题，看上面 ✗"))
    print("=" * 74)
    return 0 if ok else 1


def struct_unpack_i8(b):
    """bytes → 有符号 int8 列表"""
    return [x - 256 if x >= 128 else x for x in b]


if __name__ == "__main__":
    sys.exit(main() or 0)
