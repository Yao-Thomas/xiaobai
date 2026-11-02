#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_gpubatch.py —— 验证 C 批量驱动 + 量出每个矩形的真实开销"""
import random
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui
from gpufill import GpuFill

scr = fbui.Screen()
gf = GpuFill(scr)
if not gf.hw:
    print("!! GPU 不可用:", gf.why)
    sys.exit(1)

W, H = scr.w, scr.h

# --- 1) 整屏填充 ---
gf.begin()
gf.rect(0, 0, W - 1, H - 1, 0x102040)
t0 = time.time()
gf.commit()
t1 = time.time()
print("整屏填充 : %d 次, %d 像素, 硬件 %.2f ms, 墙钟 %.2f ms"
      % (gf.n_ops, gf.px, gf.ms, (t1 - t0) * 1000))

# --- 2) 俄罗斯方块规模: 200 个小方块 ---
random.seed(1)
rects = []
for i in range(200):
    x = random.randrange(0, W - 30)
    y = random.randrange(0, H - 30)
    rects.append((x, y, x + 27, y + 27, random.randrange(0xFFFFFF)))

t0 = time.time()
gf.begin()
for (x0, y0, x1, y1, c) in rects:
    gf.rect(x0, y0, x1, y1, c)
gf.commit()
t1 = time.time()
print("200 个 28x28 方块: %d 次, %d 像素, 硬件 %.2f ms, 墙钟 %.2f ms"
      % (gf.n_ops, gf.px, gf.ms, (t1 - t0) * 1000))
print("   -> 每个操作 %.1f 微秒 (含 Python 组数组 + 一次 C 调用)"
      % ((t1 - t0) * 1e6 / 200))

# --- 3) 1000 个方块 (压测) ---
t0 = time.time()
gf.begin()
for i in range(1000):
    x = (i * 37) % (W - 12)
    y = (i * 53) % (H - 12)
    gf.rect(x, y, x + 11, y + 11, 0x33AA55)
gf.commit()
t1 = time.time()
print("1000 个 12x12 方块: %d 次, %d 像素, 硬件 %.2f ms, 墙钟 %.2f ms"
      % (gf.n_ops, gf.px, gf.ms, (t1 - t0) * 1000))

# --- 4) 和 Python 原驱动对比 (同一个矩形 x20) ---
try:
    from gpu import GPU
    g = GPU(0x43CB0000)
    t0 = time.time()
    for i in range(20):
        g.fill(scr.phys, scr.stride, 10 + i, 10, 200, 200, 0x808080)
    t1 = time.time()
    print("\nPython 原驱动: 20 个 200x200 矩形, 墙钟 %.2f ms -> 每个 %.0f 微秒"
          % ((t1 - t0) * 1000, (t1 - t0) * 1e6 / 20))
    t0 = time.time()
    gf.begin()
    for i in range(20):
        gf.rect(10 + i, 10, 209 + i, 209, 0x808080)
    gf.commit()
    t1 = time.time()
    print("C 批量驱动  : 20 个 200x200 矩形, 墙钟 %.2f ms -> 每个 %.0f 微秒"
          % ((t1 - t0) * 1000, (t1 - t0) * 1e6 / 20))
except Exception as ex:
    print("对比失败:", ex)

gf.close()
print("\nOK")
