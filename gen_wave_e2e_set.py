#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_wave_e2e_set.py —— 在 PC 上用交付包的 dds_sim 生成端到端测试集

════════════════════════════════════════════════════════════════════
为什么要在 PC 上生成
════════════════════════════════════════════════════════════════════
板子上没有 numpy，而交付包的 dds_sim.py 依赖 numpy。
而 end-to-end 又【必须】用他们的生成器 —— 我第一版用自己的
gen_wave（K=1.5~6、满量程幅度）做端到端，只有 35%，
换成 dds_sim 就 94.8% 了，因为分布完全不同：

    dds_sim.sample_spec():
        K    ∈ [4, 64]（对数均匀）
        amp  ∈ [45, 118]（不满量程）
        + noise_lsb / jitter / dc / gain / dither

所以：PC 上用 dds_sim 生成原始波形 → 跑 wdens 得到 28×28 图
      → 打包成 bin → 传到板子 → 板子上只跑 PL 推理并比对类别

产物格式（交给板子侧 verify_wave_e2e_board.py）：
    magic  "WAVE" (4 字节)
    n      uint32 样本数
    然后 n 组： 784 字节图像(uint8) + 1 字节类别号

用法:
    python gen_wave_e2e_set.py --n 16 --out wave_e2e.bin
"""
import argparse
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_DELIV = os.path.join(HERE, "ai_delivery")
CLASSES = ("sine", "square", "triangle", "sawtooth", "noise",
           "clipping", "signal_loss", "duty_abnormal")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=16, help="每类多少个")
    ap.add_argument("--out", default="wave_e2e.bin")
    ap.add_argument("--seed", type=int, default=20261002)
    ap.add_argument("--path", default=DEF_DELIV)
    a = ap.parse_args()

    sys.path.insert(0, a.path)
    sys.path.insert(0, os.path.join(a.path, "03_源码"))
    sys.path.insert(0, HERE)

    import numpy as np
    from common import dds_sim as DS
    import waveform_ai as WA

    rng = np.random.default_rng(a.seed)
    recs = []
    meta = []
    for li, label in enumerate(CLASSES):
        for i in range(a.n):
            samples, spec, _ = DS.make_sample(rng, label)
            img = WA.wdens_u8(list(samples))
            recs.append((bytes(img), li))
            meta.append((label, float(spec.cycles), float(spec.amp)))

    with open(a.out, "wb") as f:
        f.write(b"WAVE")
        f.write(struct.pack("<I", len(recs)))
        for img, li in recs:
            f.write(img)
            f.write(bytes([li]))

    print("=" * 70)
    print(" 生成端到端测试集（PC 上用交付包 dds_sim）")
    print("=" * 70)
    print(" 每类 %d 个，共 %d 个样本" % (a.n, len(recs)))
    Ks = [m[1] for m in meta]
    amps = [m[2] for m in meta]
    print(" K 范围   : %.1f ~ %.1f" % (min(Ks), max(Ks)))
    print(" amp 范围 : %.1f ~ %.1f" % (min(amps), max(amps)))
    print(" 输出     : %s  (%d 字节)"
          % (a.out, 8 + len(recs) * 785))
    print()
    print(" 类别分布:")
    for li, label in enumerate(CLASSES):
        print("   %-15s %d" % (label, a.n))
    print()
    print(" 前端 12 个样本的参考:")
    for i, (lb, K, amp) in enumerate(meta[:12]):
        print("   #%2d %-14s K=%5.1f amp=%5.1f" % (i, lb, K, amp))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
