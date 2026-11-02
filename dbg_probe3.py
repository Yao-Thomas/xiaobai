#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_probe3.py —— 修正版探针（★ 上一版我自己把 int8 写错了）

════════════════════════════════════════════════════════════════════
上一版的错误（记下来，免得再犯）
════════════════════════════════════════════════════════════════════
我写  c.img.write(bytes([255]) * 784)  想表达"输入 = 127"，
但缓冲区里存的是【原始字节】，加速器按 int8 解释：
    0xFF → -1        ← 不是 127！
    128+x → x-256    ← 写成斜坡结果全是负数
⇒ 累加和全负 → ReLU → 全 0
⇒ 我以为是硬件坏了，其实是我探针写错了。

正确的写法：
    int8 = +x   → 写字节 x        （0..127 范围内，u8 和 int8 数值相同）
    int8 = -x   → 写字节 256-x
    int8 = 127  → 写字节 127
    int8 = -128 → 写字节 128

用法:
    sudo python3 dbg_probe3.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")


def i8_to_byte(v):
    """int8 值 → 存进缓冲区的原始字节"""
    return v & 0xFF


def byte_to_i8(b):
    return b - 256 if b >= 128 else b


def main():
    import cnn_linux as CL

    print("=" * 72)
    print(" conv1 探针（修正版：输入按 int8 正确构造）")
    print("=" * 72)

    c = CL.Cnn(verbose=False)
    IH = IW = 28
    MFQ_PROBE = 65536          # q = acc 原值

    # ── 探针 A：x 方向斜坡，int8 = x（0..27，全正）──
    print()
    print("─" * 72)
    print(" 探针 A：img[y][x] 的 int8 = x   （0..27，全正）")
    print(" 权重：只给 oc=0 全 1；MFQ=65536 → q = 累加和")
    print(" 理论：conv(oy,ox) = 3行 × (x + x+1 + x+2) = 9(ox+1)")
    print("       池化取 max → f1[0][py][px] = min(127, 18(px+1))")
    print(" 预期：18 36 54 72 90 108 126 127 127 127 127 127 127")

    img = bytearray(IH * IW)
    for y in range(IH):
        for x in range(IW):
            img[y * IW + x] = i8_to_byte(x)          # ★ int8 = x
    c.img.write(bytes(img))
    c.img.flush()
    w1 = bytearray(72)
    for k in range(9):
        w1[0 * 9 + k] = 1
    c.w1.write(bytes(w1))
    c.w1.flush()

    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f1 = [byte_to_i8(x) for x in c.fb1.read(CL.N1)]
    print()
    print("  ★ 实测 f1[oc=0]（13×13）：")
    for y in range(13):
        row = f1[y * 13: y * 13 + 13]
        print("    y=%2d: %s" % (y, " ".join("%3d" % v for v in row)))
    exp = [min(127, 18 * (px + 1)) for px in range(13)]
    got0 = f1[0:13]
    print("  理论: %s" % exp)
    print("  实测: %s" % got0)
    m = sum(1 for i in range(13) if got0[i] == exp[i])
    print("  ★ 对上 %d/13 %s" % (m, "✓✓✓" if m == 13 else ""))

    # ── 探针 B：全 127 ──
    print()
    print("─" * 72)
    print(" 探针 B：全 127（int8）→ 期望 f1 全 127")
    c.img.write(bytes([i8_to_byte(127)]) * (IH * IW))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f2 = [byte_to_i8(x) for x in c.fb1.read(CL.N1)]
    from collections import Counter
    print("  值分布: %s" % dict(Counter(f2).most_common(5)))
    all127 = all(v == 127 for v in f2)
    print("  %s" % ("✓ 全部 127" if all127 else "★ 不是全 127"))

    # ── 探针 C：全 0 ──
    print()
    print("─" * 72)
    print(" 探针 C：全 0（int8）→ 期望 f1 全 0")
    c.img.write(bytes([0]) * (IH * IW))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f3 = [byte_to_i8(x) for x in c.fb1.read(CL.N1)]
    nz = sum(1 for v in f3 if v)
    print("  非零 %d / %d  %s" % (nz, CL.N1,
                                "✓ 全 0" if nz == 0 else "★ 有非零"))

    # ── 探针 D：全 -128（最负）→ 期望 f1 全 0（ReLU 压掉）──
    print()
    print("─" * 72)
    print(" 探针 D：全 -128（int8）→ 期望 f1 全 0（ReLU）")
    c.img.write(bytes([i8_to_byte(-128)]) * (IH * IW))
    c.img.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f4 = [byte_to_i8(x) for x in c.fb1.read(CL.N1)]
    nz4 = sum(1 for v in f4 if v)
    print("  非零 %d / %d  %s" % (nz4, CL.N1,
                                "✓ 全 0" if nz4 == 0 else "★ 有非零"))

    # ── 探针 E：通道隔离（每通道不同权重）──
    print()
    print("─" * 72)
    print(" 探针 E：常数输入 + 每通道不同权重 → 看通道布局")
    VAL = 20                       # int8 = 20
    c.img.write(bytes([i8_to_byte(VAL)]) * (IH * IW))
    c.img.flush()
    w1e = bytearray(72)
    for oc in range(8):
        for k in range(9):
            w1e[oc * 9 + k] = oc + 1
    c.w1.write(bytes(w1e))
    c.w1.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    f5 = [byte_to_i8(x) for x in c.fb1.read(CL.N1)]
    print("  输入 int8=%d，权重 w1[oc][*]=oc+1" % VAL)
    print("  期望每通道一个常数：acc = %d × 9 × (oc+1)" % VAL)
    for oc in range(8):
        expv = min(127, VAL * 9 * (oc + 1))
        seg = f5[oc * 169:(oc + 1) * 169]
        uniq = sorted(set(seg))
        print("    oc=%d 期望 %3d  实测去重 %s  %s"
              % (oc, expv, uniq[:5],
                 "✓" if uniq == [expv] else "★"))

    c.close()
    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
