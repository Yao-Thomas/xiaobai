#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flicker.py —— 连续抓多帧, 定位"哪里在闪"

用法: python flicker.py mc      或   python flicker.py fight
"""
import sys
import time

from PIL import ImageChops

sys.path.insert(0, ".")
from mc_lab import Board

which = sys.argv[1] if len(sys.argv) > 1 else "mc"
runfile = "run_mc.py" if which == "mc" else "run_fight.py"
pausef = "/tmp/mc_pause" if which == "mc" else "/tmp/fight_pause"

b = Board()
b.sudo("systemctl stop zynq-desktop zynq-screen-guard")
b.sudo("pkill -9 -x python3; rm -f /tmp/mc_pause /tmp/fight_pause")
time.sleep(1)
b.sudo("cd /home/zynq/ui && (setsid nohup python3 %s 120 "
       ">/tmp/%s.log 2>&1 </dev/null &) ; echo go" % (runfile, which), 25)
time.sleep(8)

N = 8
ims = []
for i in range(N):
    ims.append(b.shot("fl_%d.png" % i, freeze=True))
    time.sleep(0.25)

b.sudo("pkill -9 -f %s; pkill -9 -x python3; rm -f %s" % (runfile, pausef), 25)
b.sudo("systemctl start zynq-screen-guard zynq-desktop; echo restored", 30)
b.close()

print("相邻帧差分的【变化区域】:")
for i in range(1, N):
    d = ImageChops.difference(ims[i - 1], ims[i]).convert("L")
    px = d.load()
    W, H = d.size
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    n = 0
    for y in range(96, H):                 # 跳过 HUD
        for x in range(0, W):
            if px[x, y] > 8:
                n += 1
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if n == 0:
        print("  帧%d->%d : 完全一样" % (i - 1, i))
    else:
        print("  帧%d->%d : %6d 像素   区域 x %d..%d  y %d..%d"
              % (i - 1, i, n, x0, x1, y0, y1))
