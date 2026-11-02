#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_pan.py —— 量 翻页(pan) 和 写显存 的真实开销"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui

scr = fbui.Screen()
W, H = scr.w, scr.h
print("fb %dx%d virt=%d stride=%d 当前页 yoff=%d" % (W, H, scr.vh, scr.stride, scr.yoff))

N = 30


def t(label, fn, n=N):
    fn()
    t0 = time.time()
    for _ in range(n):
        fn()
    dt = (time.time() - t0) * 1000.0 / n
    print("  %-34s %8.2f ms" % (label, dt))
    return dt


def pan0():
    scr.pan(0)


def pan600():
    scr.pan(600)


def blit_page0():
    scr.yoff = 0
    scr.blit_raw(0, 0, W, 96, scr.to_raw(scr.img.crop((0, 0, W, 96))))


print("\n--- 翻页 ---")
a = t("pan(0)", pan0, 20)
b = t("pan(600)", pan600, 20)
print("  -> 一次翻页约 %.1f ~ %.1f ms  (60Hz 一帧是 16.7ms)" % (min(a, b), max(a, b)))

print("\n--- 写显存 (同一块 1024x96) ---")
raw = scr.to_raw(scr.img.crop((0, 0, W, 96)))
scr.yoff = 0
c = t("blit_raw 到第 1 页", lambda: scr.blit_raw(0, 0, W, 96, raw), 30)
scr.yoff = 600
d = t("blit_raw 到第 2 页", lambda: scr.blit_raw(0, 0, W, 96, raw), 30)
print("  -> 第2页比第1页 %s" % ("慢 %.1f ms" % (d - c) if d > c + 0.3 else "一样快"))

scr.pan(0)
