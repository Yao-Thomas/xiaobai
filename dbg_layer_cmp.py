#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_layer_cmp.py —— 缓存修好后，逐层比对（终于能信读回了）

════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════
缓存问题修好后（缓冲改走不可缓存的 /dev/mem 映射）：
    组 2/3/4/5/6 全部 ✓ 与 CPU 一致
    只有组 1（波形输入 + 波形权重 + 逐层 MFQ）✗

而且已排除溢出（余量 207×/227×/144×）。

现在读回可靠了，所以逐层看：f1 对不对？f2 对不对？logits 对不对？
这样一眼看出是哪一层开始偏的。

用法:
    sudo python3 dbg_layer_cmp.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
W = "/home/zynq"


def b2i(b):
    return [x - 256 if x >= 128 else x for x in b]


def cmp_layer(name, hw, cpu):
    same = sum(1 for i in range(len(cpu)) if hw[i] == cpu[i])
    n = len(cpu)
    print("  %-10s 一致 %4d/%4d  (%.1f%%)   硬件 max=%d   CPU max=%d"
          % (name, same, n, same * 100.0 / n, max(hw), max(cpu)))
    if same != n:
        bad = [i for i in range(n) if hw[i] != cpu[i]]
        print("     前 10 个不一致的下标: %s" % bad[:10])
        for i in bad[:6]:
            print("       idx=%4d  硬件=%4d  CPU=%4d  差 %d"
                  % (i, hw[i], cpu[i], hw[i] - cpu[i]))
        # 差值的分布
        from collections import Counter
        diffs = Counter(hw[i] - cpu[i] for i in bad)
        print("     差值分布（前 8）: %s" % dict(diffs.most_common(8)))
    return same == n


def main():
    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()
    rout = open(os.path.join(W, "wave_reference_out.bin"), "rb").read()

    W1 = wb[0x0000:0x0000 + 72]
    W2 = wb[0x0080:0x0080 + 1152]
    WF = wb[0x0500:0x0500 + 3200]
    w1i, w2i, wfi = b2i(W1), b2i(W2), b2i(WF)

    print("=" * 74)
    print(" 逐层比对（第 0 组 reference）")
    print("=" * 74)

    c = CL.Cnn(verbose=False)
    c.w1.write(W1 + b"\x00" * (128 - 72))
    c.w2.write(W2)
    c.wf.write(WF + b"\x00" * (4032 - 3200))
    c.w1.flush(); c.w2.flush(); c.wf.flush()

    img = rin[0:784]
    img_i8 = b2i(img)
    print("  输入: min=%d max=%d  非零 %d/784"
          % (min(img_i8), max(img_i8), sum(1 for v in img_i8 if v)))
    print()

    # ── 逐层跑，每层都读回来比 ──
    print("【1】conv1（MFQ=%d）" % CL.MFQ_C1)
    c.img.write(img + b"\x00" * (832 - 784))
    c.img.flush()
    c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.fb1.invalidate()
    hw_f1 = b2i(c.fb1.read(CL.N1))
    cpu_f1, _, _ = CL.cpu_reference(img_i8, w1i, w2i, wfi,
                                    mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
                                    mfqfc=CL.MFQ_FC, fco=8)
    ok1 = cmp_layer("f1", hw_f1, cpu_f1)

    print()
    print("【2】conv2（MFQ=%d）" % CL.MFQ_C2)
    c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
    c.fb2.invalidate()
    hw_f2 = b2i(c.fb2.read(CL.N2))
    _, cpu_f2, _ = CL.cpu_reference(img_i8, w1i, w2i, wfi,
                                       mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
                                       mfqfc=CL.MFQ_FC, fco=8)
    ok2 = cmp_layer("f2", hw_f2, cpu_f2)
    print("     输入给 conv2 的 f1：硬件 vs CPU 一致？%s"
          % ("是" if ok1 else "★ 否（那 conv2 的输入就已经错了）"))

    # ★ 关键对照：用【CPU 算的 f1】灌进 fb1，再跑 conv2
    print()
    print("【2b】★ 把 CPU 算的 f1 灌进 fb1，再跑 conv2（隔离 conv1 的误差）")
    c.fb1.write(bytes((v & 0xFF) for v in cpu_f1))
    c.fb1.flush()
    c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
    c.fb2.invalidate()
    hw_f2b = b2i(c.fb2.read(CL.N2))
    cmp_layer("f2(隔离)", hw_f2b, cpu_f2)

    print()
    print("【3】fc（MFQ=%d）" % CL.MFQ_FC)
    c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
    c.lg.invalidate()
    hw_lg = b2i(c.lg.read(8))
    want = b2i(rout[0:8])
    print("     硬件 logits: %s" % hw_lg)
    print("     参考 logits: %s" % want)
    print("     %s" % ("✓" if hw_lg == want else "✗"))

    print()
    print("【3b】★ 把 CPU 算的 f2 灌进 fb2，再跑 fc")
    _, _, cpu_lg = CL.cpu_reference(img_i8, w1i, w2i, wfi,
                                      mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
                                      mfqfc=CL.MFQ_FC, fco=8)
    c.fb2.write(bytes((v & 0xFF) for v in cpu_f2))
    c.fb2.flush()
    c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
    c.lg.invalidate()
    hw_lg2 = b2i(c.lg.read(8))
    print("     硬件 logits: %s" % hw_lg2)
    print("     CPU  logits: %s" % cpu_lg)
    print("     %s" % ("✓" if hw_lg2 == cpu_lg else "✗"))

    print()
    print("=" * 74)
    print(" 如果 f1 就不一致 → conv1 的问题（MFQ/权重/输入）")
    print(" 如果 f1 一致但 f2 不一致 → conv2 的问题")
    print(" 如果 f1/f2 都一致但 logits 不一致 → fc 的问题")
    print("=" * 74)

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
