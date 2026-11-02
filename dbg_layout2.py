#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_layout2.py —— conv2 的多通道激活布局到底是什么

════════════════════════════════════════════════════════════════════
已经确认
════════════════════════════════════════════════════════════════════
    conv1（inC=1）      f1 与 CPU 逐点一致 100%   ✓
    conv2（inC=8）      f2 只有 70.8%              ✗
    fc  （IN=400）      也错                       ✗

conv1 的输入是单通道 ⇒ "通道在前" 和 "通道在后" 布局【一模一样】，
所以 conv1 分不出布局。到 conv2 才第一次出现多通道输入。

试这几种把 CPU 的 f1 写进 fb1 的方式，看哪种让 conv2 的输出对上：

    L1  [ic][y][x]        （通道在前）—— 我现在的做法
    L2  [y][x][ic]        （通道在后）
    L3  [ic][y][x] 但通道步长按 16 补（对齐假设）
    L4  [y][x][ic] 但按 16 通道补
    L5  [ic][y][x] 通道顺序反转

用法:
    sudo python3 dbg_layout2.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
W = "/home/zynq"
C1, H1, W1_ = 8, 13, 13
C2, H2, W2_ = 16, 5, 5


def b2i(b):
    return [x - 256 if x >= 128 else x for x in b]


def main():
    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()
    W1b = wb[0x0000:0x0000 + 72]
    W2b = wb[0x0080:0x0080 + 1152]
    WFb = wb[0x0500:0x0500 + 3200]
    w2i = b2i(W2b)

    print("=" * 74)
    print(" conv2 的多通道激活布局")
    print("=" * 74)

    c = CL.Cnn(verbose=False)
    c.w2.write(W2b)
    c.w2.flush()

    # 用 CPU 算一份正确的 f1 / f2
    img_i8 = b2i(rin[0:784])
    f1_cpu, f2_cpu, _ = CL.cpu_reference(
        img_i8, b2i(W1b), w2i, b2i(WFb),
        mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2, mfqfc=CL.MFQ_FC, fco=8)
    print("  CPU f1: %d 个值, max=%d" % (len(f1_cpu), max(f1_cpu)))
    print("  CPU f2: %d 个值, max=%d" % (len(f2_cpu), max(f2_cpu)))
    print()

    def to_bytes(vals):
        return bytes((v & 0xFF) for v in vals)

    def chw_to_hwc(vals, C, H, Wd):
        out = [0] * (C * H * Wd)
        for cc in range(C):
            for y in range(H):
                for x in range(Wd):
                    out[(y * Wd + x) * C + cc] = vals[cc * H * Wd + y * Wd + x]
        return out

    def hwc_to_chw(vals, C, H, Wd):
        out = [0] * (C * H * Wd)
        for cc in range(C):
            for y in range(H):
                for x in range(Wd):
                    out[cc * H * Wd + y * Wd + x] = vals[(y * Wd + x) * C + cc]
        return out

    def pad_channels(vals, C, H, Wd, Cpad):
        out = [0] * (Cpad * H * Wd)
        for cc in range(C):
            for y in range(H):
                for x in range(Wd):
                    out[cc * H * Wd + y * Wd + x] = vals[cc * H * Wd + y * Wd + x]
        return out

    variants = [
        ("L1 [ic][y][x]（我现在的）", f1_cpu),
        ("L2 [y][x][ic]", chw_to_hwc(f1_cpu, C1, H1, W1_)),
        ("L3 [ic][y][x] 补到16通道", pad_channels(f1_cpu, C1, H1, W1_, 16)),
        ("L4 通道顺序反转", [f1_cpu[(C1 - 1 - cc) * H1 * W1_ + y * W1_ + x]
                          for cc in range(C1)
                          for y in range(H1) for x in range(W1_)]),
    ]

    print("  %-28s %s" % ("布局", "conv2 输出与 CPU 的一致度"))
    print("  " + "-" * 60)
    results = {}
    for name, data in variants:
        c.fb1.write(to_bytes(data) + b"\x00" * (1408 - len(data)))
        c.fb1.flush()
        c.run_cpq(H1, W1_, C1, C2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.fb2.invalidate()
        hw = b2i(c.fb2.read(400))
        same = sum(1 for i in range(400) if hw[i] == f2_cpu[i])
        results[name] = same
        print("  %-28s %3d/400  (%.1f%%)  max=%d %s"
              % (name, same, same * 100.0 / 400, max(hw),
                 "★ 全对！" if same == 400 else ""))

    print()
    best = max(results.items(), key=lambda kv: kv[1])
    print("  ★ 最像的: %s  (%d/400)" % best)
    if best[1] == 400:
        print("  ⇒ 布局就是它")
    else:
        print("  ⇒ 都不是 —— 说明不是布局问题，得看别处")
        print("     （比如 conv2 读的基址、或者 w2 的排布）")

    # ── 再看：w2 的排布会不会是别的顺序 ──
    print()
    print("─" * 74)
    print(" 试 w2 的不同排布（用正确的 f1）")
    c.fb1.write(to_bytes(f1_cpu) + b"\x00" * (1408 - len(f1_cpu)))
    c.fb1.flush()

    def swap_oc_ic(vals, OC, IC, K, KH, KW):
        """把 w[(oc*IC+ic)*K + k] 换成 w[(ic*OC+oc)*K + k]"""
        out = [0] * len(vals)
        for oc in range(OC):
            for ic in range(IC):
                for k in range(K):
                    out[(ic * OC + oc) * K + k] = vals[(oc * IC + ic) * K + k]
        return out

    w2_variants = [
        ("W-a 原样 (oc,ic)", W2b),
        ("W-b 换成 (ic,oc)", to_bytes(swap_oc_ic(w2i, 16, 8, 9, 3, 3))),
        ("W-c 反过来写 (oc,ic)", to_bytes(w2i[::-1])),
    ]
    for name, wb2 in w2_variants:
        c.w2.write(wb2 + b"\x00" * (1152 - len(wb2)))
        c.w2.flush()
        c.run_cpq(H1, W1_, C1, C2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.fb2.invalidate()
        hw = b2i(c.fb2.read(400))
        same = sum(1 for i in range(400) if hw[i] == f2_cpu[i])
        print("  %-28s %3d/400 %s" % (name, same,
                                     "★ 全对！" if same == 400 else ""))

    c.close()
    print()
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
