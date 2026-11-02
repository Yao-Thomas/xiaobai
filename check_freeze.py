#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_freeze.py —— 验证"冻结截图"真的抓到完整帧"""
import sys
import time

from PIL import ImageChops

sys.path.insert(0, ".")
from mc_lab import Board

b = Board()
b.sudo("systemctl stop zynq-desktop zynq-screen-guard; pkill -9 -x python3; "
       "rm -f /tmp/mc_fps", 25)
time.sleep(1)
b.sudo("cd /home/zynq/ui && (setsid nohup python3 run_mc.py 90 "
       ">/tmp/mc.log 2>&1 </dev/null &) ; echo go", 25)
time.sleep(9)
ims = [b.shot("fz%d.png" % i, freeze=True) for i in range(3)]
b.sudo("pkill -CONT -x python3", 20)
b.sudo("pkill -9 -f run_mc.py; pkill -9 -x python3; "
       "systemctl start zynq-screen-guard zynq-desktop; echo restored", 30)
b.close()

for i in range(1, 3):
    d = ImageChops.difference(ims[0], ims[i]).convert("L")
    n = sum(1 for v in d.getdata() if v > 6)
    print("冻结帧 0 vs %d : 不同像素 %d" % (i, n))
