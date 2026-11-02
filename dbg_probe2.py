#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_probe2.py —— 用「直接读累加器」的方式把 conv1 彻底看穿

════════════════════════════════════════════════════════════════════
核心技巧
════════════════════════════════════════════════════════════════════
requant 是  q = (acc * MFQ) >> 16
如果令 **MFQ = 65536 = 2¹⁶**，那么  q = acc 原值（只受 [0,127] 截断）
⇒ ★ 就能直接读出加速器算出来的累加和，不用猜

探针：x 方向斜坡
    img[y][x] = 128 + x      → int8 = x  (0..27)
    w1[oc][ky][kx] = 1        （只测 oc=0）
    MFQ = 65536

    理论推导：
      conv(oy,ox) = Σ_{ky,kx} img[oy+ky][ox+kx]
                  = 3 × ( ox + (ox+1) + (ox+2) )      ← 3 行都一样
                  = 9 × (ox + 1)
      池化 2×2：取 (ox=2px, 2px+1) 中较大者 → ox=2px+1
      f1[0][py][px] = min(127, 18 × (px+1))

    预期（oc=0 的 13×13）：
       px:   0   1   2   3   4   5   6   7   8 ...
       值:  18  36  54  72  90 108 126 127 127 ...
      而且 ★ 每一行都一样（与 y 无关）

    如果硬件：
      · 输出全是 0            → 输入根本没读到
      · 行的方向在变           → x/y 搞反了
      · 值对但位置错           → 输出布局不是 [oc][y][x]
      · 值差一个固定倍数       → 权重或排布有问题

用法:
    sudo python3 dbg_probe2.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")


def dump(flat, off, C, H, W, name, maxoc=3):
    print("  %s（按 [oc][y][x]，显示前 %d 个通道）" % (name, maxoc))
    for oc in range(min(C, maxoc)):
        print("    oc=%d" % oc)
        for y in range(H):
            row = flat[off + oc * H * W + y * W:
                       off + oc * H * W + y * W + W]
            print("      " + " ".join("%3d" % v for v in row))


def main():
    import cnn_linux as CL

    print("=" * 72)
    print(" conv1 累加器直读探针（MFQ=65536）")
    print("=" * 72)

    c = CL.Cnn(verbose=False)
    IH = IW = 28

    # ── 斜坡输入 ──
    img = bytearray(IH * IW)
    for y in range(IH):
        for x in range(IW):
            img[y * IW + x] = 128 + x          # int8 = x
    c.img.write(bytes(img))
    c.img.flush()

    # ── 权重：oc=0 全 1，其余全 0 ──
    w1 = bytearray(72)
    for k in range(9):
        w1[0 * 9 + k] = 1
    c.w1.write(bytes(w1))
    c.w1.flush()

    print()
    print("  输入: img[y][x] = 128+x  (int8 = x, 0..27)")
    print("  权重: 只给 oc=0 全 1")
    print("  理论: f1[0][py][px] = min(127, 18×(px+1))，且每行相同")
    print("  预期 px:  18  36  54  72  90 108 126 127 127 127 127 127 127")

    MFQ_PROBE = 65536
    print()
    print("  用 MFQ=%d 跑 …" % MFQ_PROBE)
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    raw = list(c.fb1.read(CL.N1))
    f1 = [x - 256 if x >= 128 else x for x in raw]

    print()
    print("  ★ 实测 f1[oc=0] 的 13×13：")
    for y in range(13):
        row = f1[0 * 169 + y * 13: 0 * 169 + y * 13 + 13]
        print("    y=%2d: %s" % (y, " ".join("%3d" % v for v in row)))

    print()
    print("  行内是否一致（应该每行都一样）？")
    rows = [f1[y * 13: y * 13 + 13] for y in range(13)]
    allsame = all(r == rows[0] for r in rows)
    print("    %s" % ("✓ 13 行完全相同" if allsame else "★ 行与行不同"))
    if not allsame:
        for y in range(4):
            print("      y=%d: %s" % (y, rows[y]))

    print()
    print("  第 0 行 vs 理论值：")
    exp = [min(127, 18 * (px + 1)) for px in range(13)]
    print("    实测: %s" % rows[0])
    print("    理论: %s" % exp)
    match = sum(1 for i in range(13) if rows[0][i] == exp[i])
    print("    ★ 对上 %d/13" % match)

    print()
    print("  如果按 [y][x][oc] 解释呢（取每组的第 0 个通道）：")
    alt = [f1[(y * 13 + x) * 8] for y in range(1) for x in range(13)]
    print("    第 0 行: %s" % alt)

    # ── 再试 y 方向斜坡，看会不会换行变 ──
    print()
    print("─" * 72)
    print(" 对照：y 方向斜坡（img[y][x] = 128+y）")
    img2 = bytearray(IH * IW)
    for y in range(IH):
        for x in range(IW):
            img2[y * IW + x] = 128 + y
    c.img.write(bytes(img2))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f1b = [x - 256 if x >= 128 else x for x in c.fb1.read(CL.N1)]
    print("  ★ 实测 f1[oc=0]：")
    for y in range(13):
        row = f1b[0 * 169 + y * 13: 0 * 169 + y * 13 + 13]
        print("    y=%2d: %s" % (y, " ".join("%3d" % v for v in row)))
    print("  理论：沿 y 递增、每行内相同")
    print("    y=0: 9×3=27 左右；y 每 +1，值增加 18（跨 2 行池化 → 每 py 增 3×3×2=18）")

    # ── 全 0 输入对照 ──
    print()
    print("─" * 72)
    print(" 对照：全 0 输入（u8=128）→ 期望 f1 全 0")
    c.img.write(bytes([128]) * (IH * IW))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f0 = [x - 256 if x >= 128 else x for x in c.fb1.read(CL.N1)]
    nz = sum(1 for v in f0 if v)
    print("  非零个数 = %d / %d  %s" % (nz, CL.N1,
                                      "✓ 全 0" if nz == 0 else "★ 不是全 0!"))
    if nz:
        print("  前 40 个: %s" % f0[:40])

    # ── 全 255 输入对照 ──
    print()
    print("─" * 72)
    print(" 对照：全 255 输入（int8=127）→ 期望 f1 全被截到 127")
    c.img.write(bytes([255]) * (IH * IW))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f9 = [x - 256 if x >= 128 else x for x in c.fb1.read(CL.N1)]
    from collections import Counter
    print("  值的分布: %s" % dict(Counter(f9).most_common(6)))
    print("  期望全部 = 127（9×127=1143 > 127）")

    c.close()
    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
