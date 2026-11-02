#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gpu_vs_cpu.py —— 同样填满整屏, FPGA GPU vs CPU, 到底谁快"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui
from gpufill import GpuFill

scr = fbui.Screen()
W, H = scr.w, scr.h
gf = GpuFill(scr)
print("GPU 可用:", gf.hw)

N = 10


def t(label, fn, n=N):
    fn()
    t0 = time.time()
    for _ in range(n):
        fn()
    dt = (time.time() - t0) * 1000.0 / n
    print("  %-32s %8.2f ms   (%6.1f MB/s)" % (label, dt, W * H * 3 / dt / 1000.0))
    return dt


# CPU: 用 C 写的 fill_raw (纯内存写)
a = t("CPU  fill_raw 整屏 1024x600", lambda: scr.fill_raw(0, 0, W, H, 0x102040))
# CPU: 用 C 的 memcpy 路径 (blit_raw 同色)
row = bytes([0x40, 0x20, 0x10]) * W
b = t("CPU  blit_raw 整屏(预生成字节)", lambda: scr.blit_raw(0, 0, W, H, row * H))
# GPU: 硬件填
c = None
if gf.hw:
    def g():
        gf.begin()
        gf.rect(0, 0, W - 1, H - 1, 0x102040)
        gf.commit()
    c = t("FPGA GPU fill 整屏", g, 10)

if c:
    print("\n  结论: GPU %.2f ms  vs  CPU %.2f ms  ->  CPU %s %.1f 倍"
          % (c, a, "快" if a < c else "慢", max(a, c) / min(a, c)))

# 大量小矩形: GPU 的"一行一次握手"在这种场景才可能赢
print("\n--- 500 个 40x40 方块 ---")
import random
random.seed(3)
rects = [(random.randrange(0, W - 40), random.randrange(0, H - 40)) for _ in range(500)]


def gpu_many():
    gf.begin()
    for (x, y) in rects:
        gf.rect(x, y, x + 39, y + 39, 0x3060A0)
    gf.commit()


def cpu_many():
    for (x, y) in rects:
        scr.fill_raw(x, y, 40, 40, 0x3060A0)


if gf.hw:
    d = t("FPGA GPU 500 个方块", gpu_many, 5)
    e = t("CPU 500 个方块", cpu_many, 3)
    print("  -> GPU %.1f ms  CPU %.1f ms  (GPU %s)"
          % (d, e, "快 %.1f 倍" % (e / d) if d < e else "慢 %.1f 倍" % (d / e)))

gf.close()
