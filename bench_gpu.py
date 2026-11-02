#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_gpu.py —— 量一下自研 FPGA GPU 到底值不值得用

必须先把桌面停掉:  sudo systemctl stop zynq-desktop
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui

W, H = 1024, 600
N = 20


def t(label, fn, n=N):
    fn()
    t0 = time.time()
    for _ in range(n):
        fn()
    dt = (time.time() - t0) * 1000.0 / n
    print("  %-38s %8.2f ms" % (label, dt))
    return dt


def main():
    scr = fbui.Screen()
    print("fb %dx%d stride=%d phys=0x%08X" % (scr.w, scr.h, scr.stride, scr.phys or 0))

    from gpu import find_gpu
    g = find_gpu()
    if not g:
        print("!! 没找到 GPU, 只能测软件路径")
    else:
        scr.attach_gpu(g)

    print("\n--- 全屏纯色填充 1024x600 (1.84 MB) ---")
    a = b = c = None
    if scr.gpu is not None:
        a = t("FPGA GPU  fill (硬件)",
              lambda: scr.gpu.fill(scr.phys, scr.stride, 0, 0, W, H, 0x102040), 10)
    b = t("Python    fill_raw (mmap 循环)", lambda: scr.fill_raw(0, 0, W, H, 0x102040))
    c = t("PIL       d.rectangle + flush()",
          lambda: (scr.d.rectangle([0, 0, W - 1, H - 1], fill=(16, 32, 64)),
                   scr.flush()), 10)

    print("\n--- 顶栏 1024x96 (295 KB) ---")
    if scr.gpu is not None:
        t("FPGA GPU  fill (硬件)",
          lambda: scr.gpu.fill(scr.phys, scr.stride, 0, 0, W, 96, 0x080A12))
    t("Python    fill_raw (mmap 循环)", lambda: scr.fill_raw(0, 0, W, 96, 0x080A12))
    t("PIL       flush(box)", lambda: scr.flush(box=(0, 0, W, 96)))

    print("\n--- 小矩形 240x160 (115 KB) ---")
    if scr.gpu is not None:
        t("FPGA GPU  fill (硬件)",
          lambda: scr.gpu.fill(scr.phys, scr.stride, 100, 100, 240, 160, 0x224466))
    t("Python    fill_raw (mmap 循环)", lambda: scr.fill_raw(100, 100, 240, 160, 0x224466))
    t("PIL       flush(box)", lambda: scr.flush(box=(100, 100, 340, 260)))

    if a and b:
        print("\n  结论: 全屏填充 GPU %.1f ms vs Python %.1f ms -> GPU 快 %.1f 倍"
              % (a, b, b / max(a, 1e-6)))
        print("        但如果内容是【图/文字/杂色】(我们的常态),")
        print("        GPU 完全帮不上, 只能用 Python 或 C 自己写。")


main()
