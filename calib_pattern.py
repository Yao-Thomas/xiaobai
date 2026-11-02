#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_pattern.py —— 显示已知色块，用来标定板子显示链路的色彩变换

════════════════════════════════════════════════════════════════════
要解决的问题
════════════════════════════════════════════════════════════════════
用户反馈：
    "为什么你看到的和我不一样啊，我的比你蓝，你的真的刚刚好"

    "我的"    = 板子实际显示（他拍的照片）
    "你的"    = 我读 /dev/fb0 得到的图像

    两者如果是同一份数据，屏幕就该和截图一致。
    实测照片里蓝色通道远超显存里的值 ⇒ 显示链路（面板/VTC/gamma）
    把颜色往冷（蓝）的方向推了。

要修就得先量出这个变换到底是多少，所以：
    ★ 在屏幕上画【已知值】的色块 → 让人拍照 → 读照片里的实际值 → 反推

色块设计（1024x600）：
    ┌──────────────────────────────────────────┐
    │ 8 级中性灰：0 36 72 108 144 180 216 255    │ ← 检查黑/白点与中性度
    ├────────┬────────┬────────┬───────────────┤
    │ 纯红255│ 纯绿255│ 纯蓝255│ 纯白255       │ ← 检查通道增益
    ├────────┴────────┴────────┴───────────────┤
    │  我设计的深蓝背景 (22,12,10)              │ ← 关键：对比"设计的"和"看到的"
    └──────────────────────────────────────────┘

用法（板子，root）:
    sudo python3 calib_pattern.py --stay 180
"""
import argparse
import mmap
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

W, H, STRIDE = 1024, 600, 3072
VH = 1200


def rd(p, d=""):
    try:
        return open(p).read().strip()
    except Exception:
        return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stay", type=int, default=180)
    a = ap.parse_args()

    yoff = 0
    try:
        yoff = int(rd("/sys/class/graphics/fb0/pan", "0,0").split(",")[1])
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

    print("=" * 66)
    print(" 显示色彩标定图（请看屏幕 / 拍照）")
    print("=" * 66)
    print("  当前显示页 yoff = %d" % yoff)

    # ── 第 1 行：8 级中性灰（R=G=B）──
    grays = [0, 36, 72, 108, 144, 180, 216, 255]
    bw = W // 8
    for i, g in enumerate(grays):
        fill(i * bw, 0, (i + 1) * bw if i < 7 else W, 200, (g, g, g))
    print("  第1行: 8 级中性灰 = %s" % grays)

    # ── 第 2 行：纯 R / G / B / W ──
    fill(0, 210, 256, 410, (255, 0, 0))        # 红
    fill(256, 210, 512, 410, (0, 255, 0))      # 绿
    fill(512, 210, 768, 410, (0, 0, 255))      # 蓝
    fill(768, 210, W, 410, (255, 255, 255))    # 白
    print("  第2行: 纯红 | 纯绿 | 纯蓝 | 纯白")

    # ── 第 3 行：实际用的背景色 ──
    #   左：我设计的主背景（暖色版）(22,12,10)
    #   中：旧版冷蓝 (10,12,22)
    #   右：中性 (18,18,18)
    fill(0, 420, 341, 600, (22, 12, 10))
    fill(341, 420, 682, 600, (10, 12, 22))
    fill(682, 420, W, 600, (18, 18, 18))
    print("  第3行: 暖背景(22,12,10) | 冷背景(10,12,22) | 中性(18,18,18)")
    mm.flush()

    print()
    print("  ★ 请拍一张屏幕照片发给我。我要用照片里的实际数值反推")
    print("    显示链路的色彩变换（面板 gamma / 色温 / 通道增益）。")
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
