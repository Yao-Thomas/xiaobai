#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_now.py —— 直接读 /dev/fb0 抓当前屏幕（只读，不改任何东西）"""
import mmap
import sys

from PIL import Image

W, H = 1024, 600
STRIDE = int(open("/sys/class/graphics/fb0/stride").read().strip() or 3072)
BPP = int(open("/sys/class/graphics/fb0/bits_per_pixel").read().strip() or 24)
VIRT = int(open("/sys/class/graphics/fb0/virtual_size").read().split(",")[1])

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/shot_now.jpg"

f = open("/dev/fb0", "rb")
mm = mmap.mmap(f.fileno(), STRIDE * VIRT, mmap.MAP_SHARED, mmap.PROT_READ)
raw = mm[:STRIDE * H]
mm.close()
f.close()

img = Image.frombytes("RGB", (W, H), raw, "raw", "RGB", STRIDE)
img.save(out, quality=88)

# 顺便统计一下画面信息，判断是不是黑屏/花屏
px = img.load()
sample = [px[x, y] for y in range(0, H, 60) for x in range(0, W, 128)]
uniq = len(set(sample))
avg = tuple(sum(c[i] for c in sample) // len(sample) for i in range(3))
print("抓帧 -> %s  (%dx%d %dbpp stride=%d)" % (out, W, H, BPP, STRIDE))
print("  采样 %d 点，不同颜色 %d 种，平均色 RGB%s" % (len(sample), uniq, avg))
print("  判定: %s" % ("疑似黑屏/纯色" if uniq <= 3 else "有内容"))
print("SHOT_DONE")
