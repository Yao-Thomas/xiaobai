#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mc_test.py —— MC 自动化测试台 (在 PC 上跑)

用法:
    python mc_test.py idle            静置, 抓 4 张, 量"颤抖"
    python mc_test.py bench           在板子上拆解一帧各阶段耗时
    python mc_test.py exit            测"快速点左上角能不能退出"
    python mc_test.py hold X Y        手指按住不动, 抓 3 张
    python mc_test.py shot 名字        抓一张
    python mc_test.py log             看日志
"""
import os
import sys
import time

from PIL import ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_lab import Board, W, H

UI = "/home/zynq/ui"
LIMIT = 40          # MC 自动退出秒数; 测试窗口要短于它


def sh(b, cmd, t=60):
    return b.sudo(cmd, t)


def ensure_stopped(b):
    sh(b, "systemctl stop zynq-desktop")
    sh(b, "pkill -9 -f run_mc.py; killall -9 python3 2>/dev/null")
    time.sleep(1.0)
    sh(b, "rm -f /tmp/ui_tap /tmp/mc.log /tmp/mc_fps")


def ensure_started(b, limit=LIMIT):
    sh(b, "cd %s && setsid nohup python3 run_mc.py %d >/tmp/mc.log 2>&1 </dev/null &"
       % (UI, limit))
    for _ in range(40):
        time.sleep(0.5)
        if "MC START" in b.run("cat /tmp/mc.log 2>/dev/null"):
            time.sleep(2.0)
            return True
    return False


def alive(b):
    """只数 python3 进程, 避免匹配到 bash 包装"""
    n = b.run("pgrep -x python3 2>/dev/null | wc -l").strip()
    return int(n or 0)


def restore(b):
    sh(b, "pkill -9 -f run_mc.py; killall -9 python3 2>/dev/null")
    time.sleep(0.8)
    sh(b, "rm -f /tmp/ui_tap; systemctl start zynq-desktop")
    time.sleep(2.0)


def ndiff(a, b, thr=4):
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > thr else 0)
    return sum(d.histogram()[255:])


def report(imgs, thr=4):
    print("\n  帧对    变化像素     占比      最大通道差")
    for i in range(1, len(imgs)):
        n = ndiff(imgs[i - 1], imgs[i], thr)
        d = ImageChops.difference(imgs[i - 1], imgs[i])
        mx = max(d.getextrema(), key=lambda t: t[1])[1]
        print("  %d-%d   %-11d %-9s %d" % (i - 1, i, n, "%.2f%%" % (n * 100.0 / (W * H)), mx))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "idle"
    b = Board()
    ok = None
    try:
        ensure_stopped(b)
        if not ensure_started(b):
            print("!! MC 没起来, 日志:")
            print(b.run("cat /tmp/mc.log"))
            return

        if mode == "idle":
            print("\n[静置] 不碰屏幕抓 4 张, 相邻帧差异应全为 0")
            imgs = [b.shot("idle_%d.png" % i) or None for i in range(1)]
            imgs = []
            for i in range(4):
                imgs.append(b.shot("idle_%d.png" % i, freeze=True))
                time.sleep(0.7)
            report(imgs)

        elif mode == "hold":
            px, py = int(sys.argv[2]), int(sys.argv[3])
            print("\n[按住不动] down(%d,%d) 后连抓 3 张" % (px, py))
            b.ev("down", px, py)
            time.sleep(0.5)
            imgs = []
            for i in range(3):
                imgs.append(b.shot("hold_%d.png" % i, freeze=True))
                time.sleep(0.7)
            b.ev("up", px, py)
            report(imgs)

        elif mode == "jitter":
            # 模拟真实手指: 慢慢拖 + 每步 ±1~2px 噪声
            print("\n[抖动模拟] 手指缓慢拖动 + 1~2px 噪声, 抓 4 张")
            b.ev("down", 700, 320)
            time.sleep(0.3)
            imgs = []
            import random
            random.seed(7)
            cx = 700
            for i in range(4):
                for _ in range(8):
                    cx += random.choice((0, 0, 1, 1, -1, 2, -2))
                    b.ev("move", cx + random.choice((-1, 0, 1)), 320 + random.choice((-1, 0, 1)))
                    time.sleep(0.03)
                imgs.append(b.shot("jit_%d.png" % i))
            b.ev("up", cx, 320)
            report(imgs)

        elif mode == "bench":
            print("\n[耗时拆解] 在板子上单独计时各阶段")
            print(b.sudo("cd %s && python3 bench_fb.py" % UI, 120))

        elif mode == "exit":
            n0 = alive(b)
            print("\n[退出] 快速点左上角 (12,30)")
            b.tap(12, 30)
            time.sleep(3.0)
            n1 = alive(b)
            log = b.run("cat /tmp/mc.log")
            returned = "MC RETURNED ok" in log
            print("  python3 进程: 点前=%d  点后=%d" % (n0, n1))
            print("  日志有 'MC RETURNED ok': %s" % returned)
            ok = returned
            print("  结果: %s" % ("[PASS] 退出了" if returned else "[FAIL] 没退出去"))

        elif mode == "shot":
            name = sys.argv[2] if len(sys.argv) > 2 else "shot"
            b.shot(name + ".png", freeze=True)
            print("saved", name + ".png")

        elif mode == "log":
            print(b.run("cat /tmp/mc.log"))

        print("\n---- fps/耗时 ----")
        print(b.run("cat /tmp/mc_fps 2>/dev/null || echo none").strip())
    finally:
        restore(b)
        b.close()
    if ok is False:
        sys.exit(2)


main()
