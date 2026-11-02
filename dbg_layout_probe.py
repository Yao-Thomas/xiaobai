#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_layout_probe.py —— 用受控输入反推硬件的内存布局（板子上 sudo 跑）

════════════════════════════════════════════════════════════════════
思路
════════════════════════════════════════════════════════════════════
HLS 源码一时找不到，但布局可以【测出来】。

探针 1：常数输入 + 每通道不同权重
    输入图全部 = u8 200（int8 = 72）
    conv1 权重 w1[oc][0][ky][kx] = (oc+1)，9 个 tap 全一样
    ⇒ 每个通道的 acc = 72 × 9 × (oc+1)，是个只跟 oc 有关的常数
    ⇒ f1 里同一通道的所有位置应该是同一个值，8 个通道 8 个不同值
    ⇒ ★ 读回 f1，看这 8 个值【落在哪些下标】→ 直接暴露输出的通道布局
       （是 [oc][y][x] 还是 [y][x][oc]）

探针 2：单点脉冲
    输入只有 (0,0) 是 1，其余 0；权重全 1
    ⇒ 卷积只有左上角附近有响应
    ⇒ ★ 看响应落在 f1 的哪个位置 → 暴露 y/x 的顺序和 padding 行为

探针 3：x / y 方向斜坡
    输入 (y,x) = x（沿 x 递增）；权重全 1
    ⇒ ★ 如果硬件把 x/y 搞反了，输出会沿另一个方向变化

用法:
    sudo python3 dbg_layout_probe.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")


def hdr(s):
    print()
    print("─" * 70)
    print(" %s" % s)
    print("─" * 70)


def show_grid(flat, C, H, W_, name):
    """按 [oc][y][x] 假设打印"""
    print("  %s 假设布局 [oc][y][x]：" % name)
    for oc in range(min(C, 4)):
        print("    oc=%d:" % oc)
        for y in range(min(H, 5)):
            row = flat[oc * H * W_ + y * W_: oc * H * W_ + y * W_ + min(W_, 13)]
            print("      " + " ".join("%3d" % v for v in row))
    if C > 4:
        print("    (只打前 4 个通道)")


def show_channels_last(flat, C, H, W_, name):
    """按 [y][x][oc] 假设打印"""
    print("  %s 假设布局 [y][x][oc]：" % name)
    for y in range(min(H, 4)):
        for x in range(min(W_, 6)):
            base = (y * W_ + x) * C
            print("      y=%2d x=%2d → oc值 %s"
                  % (y, x, flat[base:base + C]))


def main():
    import cnn_linux as CL

    print("=" * 70)
    print(" 硬件内存布局反推")
    print("=" * 70)

    c = CL.Cnn(verbose=False)

    IH = IW = 28
    # ── 探针 1 ──
    hdr("探针 1：常数输入 + 每通道不同权重 → 暴露通道布局")
    VAL = 200                       # u8
    v_i8 = VAL - 128                # = 72
    img = bytes([VAL]) * (IH * IW)
    c.img.write(img)
    c.img.flush()

    w1 = bytearray(72)
    for oc in range(8):
        for k in range(9):
            w1[oc * 9 + k] = oc + 1        # 每通道一个不同的常数
    c.w1.write(bytes(w1))
    c.w1.flush()
    print("  输入: 全部 u8=%d (int8=%d)" % (VAL, v_i8))
    print("  权重: w1[oc][*] = oc+1  (oc=0→1, oc=7→8)")

    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.fb1.invalidate()
    f1 = list(c.fb1.read(CL.N1))
    f1 = [x - 256 if x >= 128 else x for x in f1]

    # 先算期望值
    print("  各通道期望值（acc = %d × 9 × (oc+1)）：" % v_i8)
    exp = []
    for oc in range(8):
        acc = v_i8 * 9 * (oc + 1)
        q = (acc * CL.MFQ_C1) >> 16
        q = max(0, min(127, q))
        exp.append(q)
        print("    oc=%d  acc=%6d  →  f1=%d" % (oc, acc, q))

    # 统计 f1 里出现了哪些值
    from collections import Counter
    cnt = Counter(f1)
    print("  f1 里各值出现次数（共 %d 个位置）：" % len(f1))
    for v, n in sorted(cnt.items()):
        mark = "  ← 期望之一" if v in exp else ""
        print("    值 %3d : %4d 次%s" % (v, n, mark))

    # 对每个期望值，看它落在哪些下标
    print()
    for oc in range(min(4, 8)):
        idx = [i for i, v in enumerate(f1) if v == exp[oc]]
        if idx:
            print("  期望 oc=%d 的值 %d 出现在下标 %s%s"
                  % (oc, exp[oc], idx[:8], " ..." if len(idx) > 8 else ""))
            # 按 [oc][y][x] 反推
            yx = [(i % 169) // 13, (i % 169) % 13] if idx[0] < 1352 else None
            print("     若按 [oc][y][x]：oc=%d y=%d x=%d"
                  % (idx[0] // 169, (idx[0] % 169) // 13, (idx[0] % 169) % 13))
            print("     若按 [y][x][oc]：y=%d x=%d oc=%d"
                  % (idx[0] // (13 * 8), (idx[0] // 8) % 13, idx[0] % 8))
        else:
            print("  ★ 期望 oc=%d 的值 %d 在 f1 里【找不到】" % (oc, exp[oc]))

    show_grid(f1, 8, 13, 13, "探针1")
    print()
    show_channels_last(f1, 8, 13, 13, "探针1")

    # ── 探针 2 ──
    hdr("探针 2：单点脉冲（只有 (0,0) 非零）→ 暴露 y/x 顺序")
    img2 = bytearray(IH * IW)
    img2[0] = 200                     # (y=0, x=0)
    c.img.write(bytes(img2))
    c.img.flush()
    w1b = bytes([1]) * 72              # 权重全 1
    c.w1.write(w1b)
    c.w1.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.fb1.invalidate()
    f1b = list(c.fb1.read(CL.N1))
    f1b = [x - 256 if x >= 128 else x for x in f1b]
    nz = [i for i, v in enumerate(f1b) if v]
    print("  非零位置共 %d 个" % len(nz))
    print("  按 [oc][y][x]：")
    for i in nz[:8]:
        print("    idx=%4d → oc=%d y=%2d x=%2d  (值 %d)"
              % (i, i // 169, (i % 169) // 13, (i % 169) % 13, f1b[i]))
    print("  按 [y][x][oc]：")
    for i in nz[:8]:
        print("    idx=%4d → y=%2d x=%2d oc=%d  (值 %d)"
              % (i, i // (13 * 8), (i // 8) % 13, i % 8, f1b[i]))

    # ── 探针 3 ──
    hdr("探针 3：沿 x 递增 → 看硬件有没有把 x/y 搞反")
    img3 = bytearray(IH * IW)
    for y in range(IH):
        for x in range(IW):
            img3[y * IW + x] = 128 + min(127, y * 4)     # ★ 沿 y 递增
    c.img.write(bytes(img3))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
    c.fb1.invalidate()
    f1c = list(c.fb1.read(CL.N1))
    f1c = [x - 256 if x >= 128 else x for x in f1c]
    print("  输入是【沿 y 递增】的（每一行固定值）")
    print("  如果硬件把 y/x 读对了 → f1 应该【行与行之间变化，行内不变】")
    print("  如果读反了         → f1 应该【列与列之间变化，列内不变】")
    print()
    print("  按 [oc][y][x] 打印 oc=0 的 13×13：")
    for y in range(13):
        row = f1c[0 * 169 + y * 13: 0 * 169 + y * 13 + 13]
        print("    y=%2d: %s" % (y, " ".join("%3d" % v for v in row)))
    print()
    print("  行内是否相同？")
    for y in range(4):
        row = f1c[y * 13: y * 13 + 13]
        print("    y=%d: min=%d max=%d %s"
              % (y, min(row), max(row), "→ 行内相同 ✓" if min(row) == max(row)
                 else "→ 行内不同"))
    print("  列内是否相同？（取每列的头 4 行）")
    for x in range(4):
        col = [f1c[y * 13 + x] for y in range(4)]
        print("    x=%d: %s %s" % (x, col, "→ 可能列内相同" if len(set(col)) == 1
                                   else ""))

    c.close()
    print()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
