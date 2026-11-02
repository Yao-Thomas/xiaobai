#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_wave_sync.py —— 查"为什么结果一会儿全 0 一会儿有值"

════════════════════════════════════════════════════════════════════
已知症状（dbg_wave_step.py 测出来的）
════════════════════════════════════════════════════════════════════
    conv1 849/1352（部分对，不是全错）
    conv2 351/400
    fc    0/8
    同一组连跑 3 次 → 全0 / 全0 / 有值     ← ★ 不稳定

不稳定的典型原因就三类：
    A. ap_done 已经置位 → start_and_wait 立刻返回，读的是上一次的结果
    B. 加速器写 DDR 后，CPU 读之前没失效缓存 → 读到旧值
    C. 写完寄存器后没有真正启动（ap_start 时序）

这个脚本把三种可能分开测：
    ① 同一次运行，读 5 遍（每遍 invalidate），看会不会变 → 查 B
    ② 每次运行前先清 lg，看是不是"没写"还是"写错" → 查 C
    ③ ap_ctrl 每次读回来打出来 → 查 A
    ④ 加 1ms / 10ms 延迟再读 → 查是不是"没等写完"

用法:
    sudo python3 dbg_wave_sync.py
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


def hdr(s):
    print()
    print("─" * 68)
    print(" %s" % s)
    print("─" * 68)


def main():
    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()

    print("=" * 68)
    print(" 波形模型 · 同步问题排查")
    print("=" * 68)

    c = CL.Cnn(verbose=False)
    c.w1.write(wb[0x0000:0x0000 + 72])
    c.w2.write(wb[0x0080:0x0080 + 1152])
    c.wf.write(wb[0x0500:0x0500 + 3200] + b"\x00" * (4032 - 3200))
    c.w1.flush(); c.w2.flush(); c.wf.flush()

    # ── ③ 先看 ap_ctrl 的初始态和跑完的态 ──
    hdr("③ ap_ctrl 时序（bit0=start bit1=done bit2=idle bit3=ready）")
    print("  上电后 ap_ctrl(conv) = 0x%08X" % c.cpq.r(0x00))
    print("  上电后 ap_ctrl(fc)   = 0x%08X" % c.fcq.r(0x00))

    c.img.write(rin[0:784])
    c.img.flush()
    print()
    print("  --- 只启动 conv1，逐帧看 ap_ctrl ---")
    c.cpq.w(0x00, 1)
    for i in range(12):
        ap = c.cpq.r(0x00)
        print("    +%2d×0.2ms  ap_ctrl=0x%08X  done=%d idle=%d"
              % (i, ap, (ap >> 1) & 1, (ap >> 2) & 1))
        if ap & 0x2 and i > 3:
            break
        time.sleep(0.0002)

    # ── ① 同一次运行读 5 遍 ──
    hdr("① 同一次运行，读 5 遍（每遍 invalidate）—— 查缓存")
    for trial in range(3):
        c.img.write(rin[0:784]); c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
        reads = []
        for j in range(5):
            c.lg.invalidate()
            reads.append(list(c.lg.read(8)))
            time.sleep(0.002)
        print("  第 %d 次运行，读 5 遍:" % (trial + 1))
        for j, r in enumerate(reads):
            v = [x - 256 if x >= 128 else x for x in r]
            print("     第 %d 遍: %s" % (j + 1, v))
        print("     %s" % ("✓ 5 遍一致" if all(x == reads[0] for x in reads)
                           else "★ 5 遍不一致 —— 缓存/时序问题!"))

    # ── ② 每次运行前清 lg，区分"没写" vs "写错" ──
    hdr("② 每次运行前把 lg 填成 0xAA —— 看它会不会被覆盖")
    for trial in range(3):
        c.lg.write(b"\xAA" * 8)
        c.lg.flush()
        c.img.write(rin[0:784]); c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
        c.lg.invalidate()
        r = list(c.lg.read(8))
        v = [x - 256 if x >= 128 else x for x in r]
        allaa = all(x == 0xAA for x in r)
        print("  第 %d 次: %s   %s"
              % (trial + 1, v,
                 "★ 还是 0xAA —— fc 根本没写!" if allaa else "✓ 被覆盖了"))
        time.sleep(0.01)

    # ── ④ 加延迟再读 ──
    hdr("④ 跑完加不同延迟再读 —— 查是不是没等写完")
    for delay in (0.0, 0.001, 0.01, 0.05, 0.2):
        c.img.write(rin[0:784]); c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
        time.sleep(delay)
        c.lg.invalidate()
        v = [x - 256 if x >= 128 else x for x in c.lg.read(8)]
        print("  延迟 %6.1f ms: %s" % (delay * 1000, v))

    # ── ⑤ conv1 输出也这么查一遍 ──
    hdr("⑤ conv1 的输出 fb1 稳不稳（同样读 5 遍）")
    c.img.write(rin[0:784]); c.img.flush()
    c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    prev = None
    for j in range(5):
        c.fb1.invalidate()
        r = list(c.fb1.read(CL.N1))
        if prev is None:
            print("  第 1 遍: 前12=%s  max=%d" % (r[:12], max(r)))
        else:
            n = sum(1 for i in range(CL.N1) if r[i] != prev[i])
            print("  第 %d 遍: 与上一遍差 %d 个点" % (j + 1, n))
        prev = r
        time.sleep(0.003)

    c.close()
    print()
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
