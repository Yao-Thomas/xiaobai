#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""temp_calib.py —— 用眼睛标定面板色温（不靠相机）

════════════════════════════════════════════════════════════════════
为什么不能用相机
════════════════════════════════════════════════════════════════════
拍 calib_pattern.py 那张照片时发现：
    · 屏幕上有现场反光 → 黑电平被抬高（设计 0 拍到 71）
    · 手机相机自动白平衡 → 中性灰可能被拍成任何颜色
所以照片只能定性（"偏蓝"），不能定量（偏多少）。

改成人眼判断：
    在屏幕上并排显示同一灰度、但【蓝通道逐级降低】的一排色块。
    人眼对"哪块是中性灰"非常敏感，一眼就能指出来。
    被指到的那块，蓝通道降了多少，就是面板需要的补偿量。

本次设计（两块灰度各一条，因为暗部偏蓝通常更严重）：

  ┌──────────────────────────────────────────────────────────┐
  │ 暗部：设计灰度 32，蓝通道 32 → 8 逐级降                   │
  │  [32,32,32] [32,32,28] [32,32,24] ... [32,32,8]          │
  │     0          1          2    ...     6                  │
  ├──────────────────────────────────────────────────────────┤
  │ 中部：设计灰度 112，蓝通道 112 → 64 逐级降                │
  │  [112,112,112] ... [112,112,64]                           │
  │     0                    6                                │
  ├──────────────────────────────────────────────────────────┤
  │ 亮部：设计灰度 208，蓝通道 208 → 176                      │
  └──────────────────────────────────────────────────────────┘

用法（板子，root）:
    sudo python3 temp_calib.py --stay 300
"""
import argparse
import mmap
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

W, H, STRIDE, VH = 1024, 600, 3072, 1200

# 三条彩带：(标签, 灰度基准, 蓝通道起点, 蓝通道终点, 格数)
BANDS = [
    ("暗部 基准32", 32, 32, 2, 8),
    ("中部 基准112", 112, 112, 72, 8),
    ("亮部 基准208", 208, 208, 176, 8),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stay", type=int, default=300)
    a = ap.parse_args()

    yoff = 0
    try:
        yoff = int(open("/sys/class/graphics/fb0/pan").read().strip()
                   .split(",")[1])
    except Exception:
        pass

    f = open("/dev/fb0", "r+b")
    mm = mmap.mmap(f.fileno(), STRIDE * VH, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE)

    def fill(x0, y0, x1, y1, rgb):
        px = bytes(rgb)
        row = px * (x1 - x0)
        for y in range(y0, y1):
            o = (yoff + y) * STRIDE + x0 * 3
            mm[o:o + len(row)] = row

    print("=" * 68)
    print(" 面板色温标定（用眼睛看，不用相机）")
    print("=" * 68)
    print("  当前显示页 yoff = %d" % yoff)
    print()

    band_h = H // len(BANDS)
    for bi, (label, base, b_from, b_to, n) in enumerate(BANDS):
        y0 = bi * band_h + 6
        y1 = (bi + 1) * band_h - 6
        # 每格宽度留一点间隔，方便分辨
        cw = W // n
        print("  第%d条 %s：蓝通道 %d → %d" % (bi + 1, label, b_from, b_to))
        vals = []
        for i in range(n):
            b = b_from + (b_to - b_from) * i // (n - 1)
            cols = (base, base, b)
            x0 = i * cw
            x1 = x0 + cw - 2 if i < n - 1 else W
            fill(x0, y0, x1, y1, cols)
            vals.append(b)
        print("     格号 0~%d 对应蓝通道 %s" % (n - 1, vals))

    mm.flush()
    print()
    print("  ★ 请告诉我：每一条里【哪一格看起来是真正的中性灰】")
    print("    （也就是既不偏蓝、也不偏黄的那一格，报格号就行）")
    print("  停 %d 秒 ..." % a.stay)
    try:
        time.sleep(a.stay)
    except KeyboardInterrupt:
        pass
    mm.close()
    f.close()
    print("  结束")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
