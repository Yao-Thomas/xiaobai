#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fill_fb.py —— 用洋红色填满 /dev/fb0，用来判断画面到底是"新画的"还是"旧帧残留" """
import mmap
import sys

color = sys.argv[1] if len(sys.argv) > 1 else "magenta"
RGB = {"magenta": (255, 0, 255), "green": (0, 255, 0), "black": (0, 0, 0)}[color]

W = int(open("/sys/class/graphics/fb0/virtual_size").read().split(",")[0])
VH = int(open("/sys/class/graphics/fb0/virtual_size").read().split(",")[1])
STRIDE = int(open("/sys/class/graphics/fb0/stride").read().strip())
BPP = int(open("/sys/class/graphics/fb0/bits_per_pixel").read().strip()) // 8

row = bytes(RGB) * (STRIDE // BPP) + b"\x00" * (STRIDE % BPP)
f = open("/dev/fb0", "r+b")
mm = mmap.mmap(f.fileno(), STRIDE * VH, mmap.MAP_SHARED,
               mmap.PROT_READ | mmap.PROT_WRITE)
for y in range(VH):
    mm[y * STRIDE:(y + 1) * STRIDE] = row
mm.flush()
mm.close()
f.close()
print("已用 %s 填满显存 (%dx%d stride=%d)" % (color, W, VH, STRIDE))
