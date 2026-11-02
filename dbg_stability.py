#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_stability.py —— 同一输入连跑 N 次，看结果稳不稳

现状：同一组数据，不同时候跑出来的 f1 一致度不一样（100% / 86% …）
      ⇒ 说明有非确定性因素。

这个脚本排除干扰，只做一件事：
    同一张输入图，连跑 10 次 conv1，每次读回 f1 与 CPU 参考比，
    打印每次的一致度和前几个不一致的位置。

如果 10 次结果都一样 → 说明是"状态相关"（比如上一次遗留），不是随机
如果 10 次结果乱跳   → 说明是竞争/缓存

用法:
    sudo python3 dbg_stability.py
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
W = "/home/zynq"


def b2i(b):
    return [x - 256 if x >= 128 else x for x in b]


def main():
    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()
    W1b = wb[0x0000:0x0000 + 72]
    w1i = b2i(W1b)

    img = rin[0:784]
    img_i8 = b2i(img)

    # CPU 参考
    f1_cpu = [0] * 1352
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
                                       w1i[oc * 9 + ky * 3 + kx]
                        q = (acc * CL.MFQ_C1) >> 16
                        best = max(best, max(0, min(127, q)))
                f1_cpu[oc * 169 + py * 13 + px] = best

    print("=" * 74)
    print(" 稳定性测试：同一输入连跑 10 次 conv1")
    print("=" * 74)
    print("  CPU 参考 f1 max=%d  非零 %d/1352"
          % (max(f1_cpu), sum(1 for v in f1_cpu if v)))
    print()

    c = CL.Cnn(verbose=False)
    c.w1.write(W1b + b"\x00" * (128 - 72))
    c.w1.flush()
    c.img.write(img + b"\x00" * (832 - 784))
    c.img.flush()

    print("  次  一致度      max   前 6 个不一致下标")
    print("  " + "-" * 62)
    sigs = []
    for k in range(10):
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.fb1.invalidate()
        hw = b2i(c.fb1.read(1352))
        same = sum(1 for i in range(1352) if hw[i] == f1_cpu[i])
        bad = [i for i in range(1352) if hw[i] != f1_cpu[i]]
        sig = tuple(hw[:64])
        sigs.append(sig)
        print("  %2d  %4d/1352  %5.1f%%   %3d   %s"
              % (k + 1, same, same * 100.0 / 1352, max(hw), bad[:6]))

    print()
    uniq = len(set(sigs))
    print("  前 64 字节的不同版本数: %d （10 次里）" % uniq)
    if uniq == 1:
        print("  ⇒ 每次都一样 —— 是【状态相关】，不是随机")
    else:
        print("  ⇒ 每次都不一样 —— 【非确定性】")

    # ── 再测：连续跑两次，中间不做任何事，看第二次是不是更好 ──
    print()
    print("─" * 74)
    print(" 对照：连跑两次（第二次紧接第一次，看有没有『预热』效应）")
    for trial in range(2):
        for k in range(4):
            c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
            c.fb1.invalidate()
            hw = b2i(c.fb1.read(1352))
            same = sum(1 for i in range(1352) if hw[i] == f1_cpu[i])
            print("    第%d轮 第%d次: %4d/1352 (%.1f%%)"
                  % (trial + 1, k + 1, same, same * 100.0 / 1352))

    # ── 再测：读两次（第二次紧接着第一次读，不重跑）──
    print()
    print("─" * 74)
    print(" 对照：跑一次，连读 5 遍（看是不是『读一次之后才对』）")
    c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    for k in range(5):
        c.fb1.invalidate()
        hw = b2i(c.fb1.read(1352))
        same = sum(1 for i in range(1352) if hw[i] == f1_cpu[i])
        print("    第 %d 遍读: %4d/1352 (%.1f%%)" % (k + 1, same,
                                                   same * 100.0 / 1352))
        time.sleep(0.001)

    c.close()
    print()
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
