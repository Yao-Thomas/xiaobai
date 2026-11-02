#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_fb.py —— 在板子上拆解 MC 一帧里 Python 侧各阶段的耗时

用来找 "HUD+推送 = 21ms" 到底花在哪。
必须先把桌面停掉:  sudo systemctl stop zynq-desktop
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
from PIL import Image, ImageDraw

import fbui

W, H = 1024, 600
N = 30


def t(label, fn, n=N):
    fn()                                  # 预热
    t0 = time.time()
    for _ in range(n):
        fn()
    dt = (time.time() - t0) * 1000.0 / n
    print("  %-34s %8.2f ms" % (label, dt))
    return dt


def main():
    scr = fbui.Screen()
    print("fb: %dx%d stride=%d phys=0x%08X gpu=%s"
          % (scr.w, scr.h, scr.stride, scr.phys or 0, scr.gpu))
    d = scr.d

    hud = Image.new("RGB", (W, 96), (8, 10, 18))
    ctrl = Image.new("RGB", (260, 184), (0, 0, 0))

    print("\n--- 各阶段单独计时 (每项 %d 次平均) ---" % N)
    t("paste HUD 1024x96", lambda: scr.img.paste(hud, (0, 0)))
    t("paste ctrl 260x184", lambda: scr.img.paste(ctrl, (W - 260, H - 184)))
    t("text ascii 19px", lambda: scr.text((16, 54), "X 123 Y 456 ALT 30 YAW 0 22 FPS",
                                          19, (235, 245, 255), bold=True))
    t("text cn 21px anchor=mm",
      lambda: scr.text((W // 2, 76), "自己写的 MC", 21, (255, 240, 170), cn=True, anchor="mm"))
    t("crop+convert 1024x96", lambda: scr.img.crop((0, 0, W, 96)).convert(scr.mode).tobytes())
    t("flush box(0,0,1024,96)", lambda: scr.flush(box=(0, 0, W, 96)))
    t("flush box(762,414,1024,600)", lambda: scr.flush(box=(W - 262, H - 186, W, H)))
    t("flush FULL 1024x600", lambda: scr.flush())

    print("\n--- 对照: GPU 硬件填充 ---")
    if scr.gpu is not None and scr.phys:
        t("gpu.fill 1024x96",
          lambda: scr.gpu.fill(scr.phys, scr.stride, 0, 0, W, 96, 0x080A12), 10)
        t("gpu.fill 1024x600",
          lambda: scr.gpu.fill(scr.phys, scr.stride, 0, 0, W, H, 0x080A12), 5)

    print("\n--- 组合: 现在的写法 vs 优化后 ---")

    def now():
        scr.img.paste(hud, (0, 0))
        scr.img.paste(ctrl, (W - 260, H - 184))
        scr.text((16, 54), "X 123 Y 456 ALT 30 YAW 0 22 FPS",
                 19, (235, 245, 255), bold=True)
        scr.flush(box=(0, 0, W, 96))
        scr.flush(box=(W - 262, H - 186, W, H))
    a = t("现在: 2 paste + text + 2 flush", now, 20)

    def opt():
        # 背景用 GPU 硬件填充, 只用 PIL 推"文字所在的小块"
        scr.fill(0, 0, W, 96, (8, 10, 18))
        scr.fill(W - 262, H - 186, 262, 186, (0, 0, 0))
        scr.img.paste(ctrl, (W - 260, H - 184))
        scr.text((16, 54), "X 123 Y 456 ALT 30 YAW 0 22 FPS",
                 19, (235, 245, 255), bold=True)
        scr.flush(box=(8, 47, 470, 78))
    c = t("优化: 2 GPU填充 + text + 1 小 flush", opt, 20)
    print("\n  提升: %.2f ms -> %.2f ms,  省下 %.2f ms/帧"
          % (a, c, a - c))


main()
