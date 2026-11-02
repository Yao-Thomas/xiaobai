#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_wave_step.py —— 波形模型上板【逐层】排查（板子上 sudo 跑）

════════════════════════════════════════════════════════════════════
为什么要有它
════════════════════════════════════════════════════════════════════
`verify_wave_onboard.py` 只告诉你"总共 3/512 对"，不告诉你断在哪一层。
这个脚本把三层拆开，每层都：

    ① 把寄存器【读回】来确认真的写进去了（MFQ 尤其重要）
    ② 跑完这一层
    ③ 把这一层的输出缓冲读回来，和 CPU 纯 Python 复刻逐点比

这样一眼就能看出是 conv1 / conv2 / fc 哪一层、或者寄存器没写进去。

用法:
    sudo python3 dbg_wave_step.py
    sudo python3 dbg_wave_step.py --k 2      # 看第几组（默认 0）
"""
import argparse
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
W = "/home/zynq"


def hdr(s):
    print()
    print("─" * 68)
    print(" %s" % s)
    print("─" * 68)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=0, help="用第几组 reference（0~63）")
    a = ap.parse_args()

    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()
    rout = open(os.path.join(W, "wave_reference_out.bin"), "rb").read()

    W1 = list(wb[0x0000:0x0000 + 72])
    W2 = list(wb[0x0080:0x0080 + 1152])
    WF = list(wb[0x0500:0x0500 + 3200])
    W1 = [x - 256 if x >= 128 else x for x in W1]
    W2 = [x - 256 if x >= 128 else x for x in W2]
    WF = [x - 256 if x >= 128 else x for x in WF]

    k = a.k
    img_i8 = list(rin[k * 784:(k + 1) * 784])      # ★ 已经是 int8
    img_i8s = [x - 256 if x >= 128 else x for x in img_i8]
    want = list(rout[k * 8:(k + 1) * 8])

    print("=" * 68)
    print(" 波形模型 · 逐层排查（第 %d 组）" % k)
    print("=" * 68)
    print(" 输入: min=%d max=%d 前 12 个=%s"
          % (min(img_i8s), max(img_i8s), img_i8s[:12]))
    print(" 期望 logits(int8): %s"
          % [x - 256 if x >= 128 else x for x in want])

    # ── CPU 复刻，作为基准 ──
    hdr("0) CPU 纯 Python 复刻（基准）")
    ref1, ref2, ref_lg = CL.cpu_reference(img_i8s, W1, W2, WF,
                                          mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
                                          mfqfc=CL.MFQ_FC, fco=8)
    print("  f1(conv1)  min=%d max=%d  前 12=%s" % (min(ref1), max(ref1), ref1[:12]))
    print("  f2(conv2)  min=%d max=%d  前 12=%s" % (min(ref2), max(ref2), ref2[:12]))
    print("  logits     %s" % ref_lg)

    # ── 开硬件 ──
    hdr("1) 硬件初始化 + 寄存器读回")
    c = CL.Cnn(verbose=False)
    c.w1.write(wb[0x0000:0x0000 + 72])
    c.w2.write(wb[0x0080:0x0080 + 1152])
    c.wf.write(wb[0x0500:0x0500 + 3200] + b"\x00" * (4032 - 3200))
    c.w1.flush()
    c.w2.flush()
    c.wf.flush()
    print("  缓冲物理地址:")
    for nm in ("img", "w1", "fb1", "w2", "fb2", "wf", "lg"):
        b = getattr(c, nm)
        # ★ 单页内的缓冲天然物理连续；跨页就得查是不是连续了
        npages = (b.size + 4095) // 4096
        print("    %-4s paddr=0x%08X size=%4d(页对齐后 %4d, %d 页)  64对齐=%s"
              % (nm, b.paddr, b.size, b.alloc, npages,
                 "是" if b.paddr % 64 == 0 else "★ 否"))

    # 把 MFQ 写进去再读回来 —— ★ 确认真的落地了
    c.cpq.w(CL.R_MFQ, CL.MFQ_C1)
    c.fcq.w(CL.F_MFQ, CL.MFQ_FC)
    rb1 = c.cpq.r(CL.R_MFQ)
    rbf = c.fcq.r(CL.F_MFQ)
    print("  cnn_conv_pool MFQ(0x6c): 写 %d 读回 %d  %s"
          % (CL.MFQ_C1, rb1, "✓" if rb1 == CL.MFQ_C1 else "★ 不一致!"))
    print("  cnn_fc        MFQ(0x44): 写 %d 读回 %d  %s"
          % (CL.MFQ_FC, rbf, "✓" if rbf == CL.MFQ_FC else "★ 不一致!"))

    # ── conv1 ──
    hdr("2) conv1（28×28×1 → 13×13×8）MFQ=%d" % CL.MFQ_C1)
    c.img.write(rin[k * 784:(k + 1) * 784])       # ★ 直接拷，不再 -128
    c.img.flush()
    # 读回输入确认
    back = c.img.read(16)
    print("  输入缓冲读回前 16 字节: %s" % list(back))
    print("  写入的前 16 字节:      %s" % list(rin[k * 784:k * 784 + 16]))
    print("  %s" % ("✓ 输入写进去了" if list(back) == list(rin[k * 784:k * 784 + 16])
                    else "★ 输入没写进去!"))

    dt1 = c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.fb1.invalidate()
    got1 = list(c.fb1.read(CL.N1))
    got1s = [x - 256 if x >= 128 else x for x in got1]
    same1 = sum(1 for i in range(CL.N1) if got1s[i] == ref1[i])
    print("  耗时 %.3f s" % dt1)
    print("  硬件 f1 前 12: %s" % got1s[:12])
    print("  CPU   f1 前 12: %s" % ref1[:12])
    print("  ★ 一致 %d/%d %s" % (same1, CL.N1,
                                "✓" if same1 == CL.N1 else "✗"))

    # ── conv2 ──
    hdr("3) conv2（13×13×8 → 5×5×16）MFQ=%d" % CL.MFQ_C2)
    dt2 = c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
    c.fb2.invalidate()
    got2 = list(c.fb2.read(CL.N2))
    got2s = [x - 256 if x >= 128 else x for x in got2]
    same2 = sum(1 for i in range(CL.N2) if got2s[i] == ref2[i])
    print("  耗时 %.3f s" % dt2)
    print("  硬件 f2 前 12: %s" % got2s[:12])
    print("  CPU   f2 前 12: %s" % ref2[:12])
    print("  ★ 一致 %d/%d %s" % (same2, CL.N2,
                                "✓" if same2 == CL.N2 else "✗"))

    # ── fc ──
    hdr("4) fc（400 → 8）MFQ=%d" % CL.MFQ_FC)
    dt3 = c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
    c.lg.invalidate()
    got3 = list(c.lg.read(8))
    got3s = [x - 256 if x >= 128 else x for x in got3]
    print("  耗时 %.3f s" % dt3)
    print("  硬件 logits: %s" % got3s)
    print("  CPU  logits: %s" % ref_lg)
    print("  参考 logits: %s" % [x - 256 if x >= 128 else x for x in want])
    print("  ★ 硬件 vs CPU : %d/8 %s"
          % (sum(1 for i in range(8) if got3s[i] == ref_lg[i]),
             "✓" if got3s == ref_lg else "✗"))
    print("  ★ CPU  vs 参考: %d/8 %s"
          % (sum(1 for i in range(8) if ref_lg[i] == (want[i] - 256 if want[i] >= 128 else want[i])),
             "✓"))

    # ── 重复跑两次，看稳不稳 ──
    hdr("5) 同一组连跑 3 次（看结果稳不稳）")
    for i in range(3):
        c.img.write(rin[k * 784:(k + 1) * 784])
        c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
        c.lg.invalidate()
        r = [x - 256 if x >= 128 else x for x in c.lg.read(8)]
        print("    第 %d 次: %s" % (i + 1, r))

    # ── 换一组的输入，看输出会不会变 ──
    hdr("6) 换第 %d 组的输入（看输出会不会变）" % (k + 1))
    c.img.write(rin[(k + 1) * 784:(k + 2) * 784])
    c.img.flush()
    c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
    c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
    c.lg.invalidate()
    r2 = [x - 256 if x >= 128 else x for x in c.lg.read(8)]
    print("    第 %d 组 logits: %s" % (k + 1, r2))
    img2 = list(rin[(k + 1) * 784:(k + 2) * 784])
    img2s = [x - 256 if x >= 128 else x for x in img2]
    _, _, lg2 = CL.cpu_reference(img2s, W1, W2, WF,
                                 mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
                                 mfqfc=CL.MFQ_FC, fco=8)
    print("    CPU 第 %d 组:    %s" % (k + 1, lg2))
    print("    %s" % ("✓ 换输入输出也变了" if r2 != got3s
                      else "★ 换了输入输出没变 —— 数据通路有问题!"))

    c.close()
    print()
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
