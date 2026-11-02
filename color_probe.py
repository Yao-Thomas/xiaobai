#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""color_probe.py —— ★ 判定板子 LCD 的像素字节序（RGB 还是 BGR）

════════════════════════════════════════════════════════════════════
为什么要测这个
════════════════════════════════════════════════════════════════════
2026-10-03 用户的疑问：
    "为什么你截屏是蓝的？你设计的是蓝色吗？为什么板子显示的是棕红色？"

推断：
    fbui.py 用 PIL 的 "BGR;24" 模式写显存（第 82 行），
    GPU 快速路径也手动写 bytes((b, g, r))（第 225 行）。
    ⇒ 如果面板其实按 RGB 解释，颜色就【红蓝互换】：
          深蓝黑 (10,12,22)  →  棕红 (22,12,10)   ← 用户看到的
          按钮蓝 (52,70,120) →  棕红 (120,70,52)  ← 用户看到的
    而我的截图读 /dev/fb0 后又把 R/B 换回来，所以截图是蓝的。

但这个推断需要【眼见为实】——
所以这个脚本往屏幕上方砸三块纯色，人眼一看就知道：

    ┌──────────┬──────────┬──────────┐
    │  块 A    │  块 B    │  块 C    │
    │  纯红    │  纯绿    │  纯蓝    │   ← 代码里"想画"的颜色
    └──────────┴──────────┴──────────┘

★ 如果屏幕上 A 是红的、C 是蓝的
    ⇒ 面板就是 BGR，fbui 是对的，不用改

★ 如果屏幕上 A 变成了蓝、C 变成了红
    ⇒ 面板是 RGB，fbui 的 "BGR;24" 是错的，红蓝一直互换
      （那整个桌面、所有 App 的颜色都是错的，不只我这个）

用法（板子上，需要 root 因为要写 /dev/fb0）:
    sudo python3 /home/zynq/color_probe.py           # 画色块，停 30 秒
    sudo python3 /home/zynq/color_probe.py --bbg     # 用 B,G,R 顺序画（BGR 假设）
"""
import argparse
import mmap
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def rd(p, d=""):
    try:
        return open(p).read().strip()
    except Exception:
        return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbg", action="store_true",
                    help="按 B,G,R 顺序写（即 fbui 现在的做法）")
    ap.add_argument("--stay", type=int, default=30,
                    help="色块保留多少秒（默认 30）")
    a = ap.parse_args()

    vs = rd("/sys/class/graphics/fb0/virtual_size", "1024,1200").split(",")
    W = int(vs[0])
    VH = int(vs[1])
    H = min(600, VH)
    bpp = int(rd("/sys/class/graphics/fb0/bits_per_pixel", "24"))
    bppx = bpp // 8
    stride = int(rd("/sys/class/graphics/fb0/stride", str(W * bppx)))

    f = open("/dev/fb0", "r+b")
    mm = mmap.mmap(f.fileno(), stride * VH, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE)

    # 当前显示页的起始偏移
    yoff = 0
    try:
        yoff = int(rd("/sys/class/graphics/fb0/pan", "0,0").split(",")[1])
    except Exception:
        pass

    print("=" * 68)
    print(" 板子 LCD 像素字节序探针")
    print("=" * 68)
    print("  分辨率 %dx%d (虚拟高 %d)  %dbpp  stride=%d  当前页 yoff=%d"
          % (W, H, VH, bpp, stride, yoff))
    print("  写入顺序: %s" % ("B,G,R  (fbui 现在的做法)" if a.bbg
                              else "R,G,B  (标准)"))
    print()

    # 三块纯色：【代码里想画的】颜色
    #   A = 纯红 (255,0,0)
    #   B = 纯绿 (0,255,0)
    #   C = 纯蓝 (0,0,255)
    colors = [("A 想画红", (255, 0, 0)),
              ("B 想画绿", (0, 255, 0)),
              ("C 想画蓝", (0, 0, 255))]
    bw = W // 3
    y0, y1 = H // 4, H * 3 // 4

    for i, (name, (r, g, b)) in enumerate(colors):
        x0 = i * bw
        x1 = (i + 1) * bw if i < 2 else W
        # ★ 按选定顺序排列字节
        px = bytes((b, g, r)) if a.bbg else bytes((r, g, b))
        row = px * (x1 - x0)
        for y in range(y0, y1):
            off = (yoff + y) * stride + x0 * bppx
            mm[off:off + len(row)] = row
    mm.flush()

    print("  三块色块已画好（屏幕上半部分，从左到右 A B C）：")
    print("      A = 代码里写的是【纯红 (255,0,0)】")
    print("      B = 代码里写的是【纯绿 (0,255,0)】")
    print("      C = 代码里写的是【纯蓝 (0,0,255)】")
    print()
    if a.bbg:
        print("  ★ fbui 的假设是 BGR —— 如果面板真是 BGR，")
        print("    屏幕上应该 A 红、B 绿、C 蓝。")
        print("    如果 A 变蓝了，说明面板是 RGB，fbui 的 BGR;24 是错的。")
    else:
        print("  ★ 这是【标准 RGB】写法 —— 如果面板是 RGB，")
        print("    屏幕上应该 A 红、B 绿、C 蓝。")
        print("    如果 A 变蓝了，说明面板是 BGR，fbui 反而是对的。")
    print()
    print("  ★ 请把屏幕上从左到右三块的颜色记下来，告诉我。")
    print("  色块保留 %d 秒 ..." % a.stay)
    try:
        time.sleep(a.stay)
    except KeyboardInterrupt:
        pass
    print("  结束（屏幕会在下次重绘时恢复）")
    mm.close()
    f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
