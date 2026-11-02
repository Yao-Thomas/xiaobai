#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_fc_only.py —— 单独把 fc 这一层钉死

════════════════════════════════════════════════════════════════════
已知
════════════════════════════════════════════════════════════════════
    conv1 写 fb1  ✓（稳定，max 和 CPU 一致）
    conv2 写 fb2  ✓（部分对）
    fc    写 lg   ✗（先把 lg 填 0xAA，跑完还是 0xAA）

所以把 fc 单独拎出来做对照实验，一次只改一个变量：

    A. 用 wave 权重 + MFQ=1390（正常路径）→ 期望写
    B. 用 wave 权重 + MFQ=119 （MNIST 的值）→ 看 MFQ 是不是关键
    C. 用 wave 权重 + MFQ=1   （极小值）→ 看会不会写了
    D. OUT=8 vs OUT=10                     → 看 OUT 参数
    E. 把整个 64 字节缓冲打出来           → 看是不是写到别的偏移去了
    F. fc 的寄存器全部读回来               → 看指针写进去没有

用法:
    sudo python3 dbg_fc_only.py
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
    print("─" * 70)
    print(" %s" % s)
    print("─" * 70)


def main():
    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()

    print("=" * 70)
    print(" fc 单层排查")
    print("=" * 70)

    c = CL.Cnn(verbose=False)
    c.w1.write(wb[0x0000:0x0000 + 72])
    c.w2.write(wb[0x0080:0x0080 + 1152])
    c.wf.write(wb[0x0500:0x0500 + 3200] + b"\x00" * (4032 - 3200))
    c.w1.flush(); c.w2.flush(); c.wf.flush()

    # 先跑一遍完整的前两层，得到真实的 f2
    c.img.write(rin[0:784]); c.img.flush()
    c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
    c.fb2.invalidate()
    f2 = list(c.fb2.read(CL.N2))
    print(" f2 已就绪: 前 12 = %s  max = %d" % (f2[:12], max(f2)))

    # ── F. fc 的寄存器全部读回来 ──
    hdr("F) fc 寄存器读回（先跑一次，看参数有没有落地）")
    c.fcq.w64(CL.F_X, c.fb2.paddr)
    c.fcq.w64(CL.F_W, c.wf.paddr)
    c.fcq.w64(CL.F_OUT, c.lg.paddr)
    c.fcq.w(CL.F_IN, CL.FCI)
    c.fcq.w(CL.F_OUTN, 8)
    c.fcq.w(CL.F_MFQ, 1390)
    print("  期望值:")
    print("    F_X  (0x10) = 0x%08X" % c.fb2.paddr)
    print("    F_W  (0x1c) = 0x%08X" % c.wf.paddr)
    print("    F_OUT(0x28) = 0x%08X" % c.lg.paddr)
    print("    F_IN (0x34) = %d" % CL.FCI)
    print("    F_OUTN(0x3c)= %d" % 8)
    print("    F_MFQ(0x44) = %d" % 1390)
    print("  读回值:")
    for nm, off in (("F_X", CL.F_X), ("F_X_HI", CL.F_X + 4),
                    ("F_W", CL.F_W), ("F_W_HI", CL.F_W + 4),
                    ("F_OUT", CL.F_OUT), ("F_OUT_HI", CL.F_OUT + 4),
                    ("F_IN", CL.F_IN), ("F_OUTN", CL.F_OUTN),
                    ("F_MFQ", CL.F_MFQ)):
        print("    %-9s (0x%02X) = 0x%08X" % (nm, off, c.fcq.r(off)))

    # ── A/B/C. MFQ 对照 ──
    hdr("A/B/C) 同一输入，只改 MFQ —— 看 lg 有没有被写")
    for mfq in (1390, 119, 1, 0):
        c.lg.write(b"\xAA" * 64)
        c.lg.flush()
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=mfq)
        c.lg.invalidate()
        raw = list(c.lg.read(64))
        v = [x - 256 if x >= 128 else x for x in raw[:8]]
        written = any(x != 0xAA for x in raw)
        print("  MFQ=%5d  %s  %s"
              % (mfq, v, "✓ 写了" if written else "★ 没写（还是 0xAA）"))

    # ── D. OUT 对照 ──
    hdr("D) 只改 OUT（输出个数）")
    for out in (8, 10, 400):
        c.lg.write(b"\xAA" * 64)
        c.lg.flush()
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, out, mfq=1390)
        c.lg.invalidate()
        raw = list(c.lg.read(64))
        v = [x - 256 if x >= 128 else x for x in raw[:8]]
        written = any(x != 0xAA for x in raw)
        print("  OUT=%3d  %s  %s"
              % (out, v, "✓ 写了" if written else "★ 没写"))

    # ── E. 扫描整个缓冲 ──
    hdr("E) 扫描 lg 缓冲的 64 字节 —— 看是不是写到别的偏移")
    c.lg.write(b"\xAA" * 64)
    c.lg.flush()
    c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=1390)
    c.lg.invalidate()
    raw = list(c.lg.read(64))
    print("  %s" % (raw[:32],))
    print("  %s" % (raw[32:],))
    print("  非 0xAA 的位置: %s"
          % ([i for i, x in enumerate(raw) if x != 0xAA] or "无"))

    # ── G. 用 CPU 已知的 f2 灌进去，排除 f2 的影响 ──
    hdr("G) 用 CPU 算的 f2 灌进 fb2，再跑 fc（排除上一层的影响）")
    W1 = [x - 256 if x >= 128 else x for x in wb[0x0000:0x0000 + 72]]
    W2 = [x - 256 if x >= 128 else x for x in wb[0x0080:0x0080 + 1152]]
    WF = [x - 256 if x >= 128 else x for x in wb[0x0500:0x0500 + 3200]]
    img_i8 = [x - 256 if x >= 128 else x for x in rin[0:784]]
    _f1, f2c, lgc = CL.cpu_reference(img_i8, W1, W2, WF,
                                     mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
                                     mfqfc=CL.MFQ_FC, fco=8)
    c.fb2.write(bytes(f2c))
    c.fb2.flush()
    c.lg.write(b"\xAA" * 64)
    c.lg.flush()
    c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
    c.lg.invalidate()
    raw = list(c.lg.read(64))
    v = [x - 256 if x >= 128 else x for x in raw[:8]]
    print("  硬件 lg: %s" % v)
    print("  CPU  lg: %s" % lgc)
    print("  %s" % ("★ 一致" if v == lgc else "✗ 不一致"))
    print("  非 0xAA 的位置: %s"
          % ([i for i, x in enumerate(raw) if x != 0xAA] or "无"))

    # ── H. 慢慢加等待，看 ap_done 到什么时候置位 ──
    hdr("H) 启动 fc 后逐帧看 ap_ctrl（这次等够 30ms）")
    c.lg.write(b"\xAA" * 64); c.lg.flush()
    c.fcq.w64(CL.F_X, c.fb2.paddr)
    c.fcq.w64(CL.F_W, c.wf.paddr)
    c.fcq.w64(CL.F_OUT, c.lg.paddr)
    c.fcq.w(CL.F_IN, CL.FCI)
    c.fcq.w(CL.F_OUTN, 8)
    c.fcq.w(CL.F_MFQ, CL.MFQ_FC)
    c.fcq.w(0x00, 1)
    t0 = time.time()
    for i in range(30):
        ap = c.fcq.r(0x00)
        if ap != 0x00000001:
            print("    +%.1f ms  ap_ctrl=0x%08X  done=%d idle=%d"
                  % ((time.time() - t0) * 1000, ap, (ap >> 1) & 1, (ap >> 2) & 1))
        if ap & 0x2 and i > 2:
            break
        time.sleep(0.001)
    print("    30 次轮询后 ap_ctrl = 0x%08X" % c.fcq.r(0x00))
    c.lg.invalidate()
    print("    lg 前 8 = %s"
          % [x - 256 if x >= 128 else x for x in c.lg.read(8)])

    c.close()
    print()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
