#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mc_play_test.py —— 前台跑 MC, 注入按键, 验证 放/挖/返回 三个动作

不开 nohup/后台, 免得进程和日志混淆。
"""
import sys
import time

from PIL import ImageChops

sys.path.insert(0, ".")
from mc_lab import Board, W, H

SECS = 45
BTN_PUT = (958, 453)      # 右下"放"
BTN_DIG = (826, 453)      # 右下"挖"
BTN_BACK = (60, 30)       # 左上"返回"


def ndiff(a, b, thr=6):
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > thr else 0)
    return sum(d.histogram()[255:])


def main():
    b = Board()
    b.sudo("systemctl stop zynq-desktop")
    b.sudo("pkill -9 -f run_mc.py; pkill -9 -x python3; rm -f /tmp/ui_tap")
    time.sleep(1.0)

    chan = b.c.get_transport().open_session()
    chan.exec_command("cd /home/zynq/ui && exec sudo python3 run_mc.py %d --events 2>&1"
                      % SECS)
    time.sleep(6.0)

    shots = {}
    shots["0_初始"] = b.shot("play_0.png")

    for label, pt in (("1_放", BTN_PUT), ("2_再放", BTN_PUT),
                      ("3_挖", BTN_DIG)):
        b.tap(*pt)
        time.sleep(1.2)
        shots[label] = b.shot("play_%s.png" % label.split("_")[0])

    order = ["0_初始", "1_放", "2_再放", "3_挖"]
    print("\n  相邻两张的变化像素数 (只统计画面区, 不含 HUD):")
    for i in range(1, len(order)):
        a = shots[order[i - 1]].crop((0, 96, W, 410))
        c = shots[order[i]].crop((0, 96, W, 410))
        n = ndiff(a, c)
        print("    %-8s -> %-8s  %7d 像素 (%.2f%%)"
              % (order[i - 1], order[i], n, n * 100.0 / ((W) * 314)))

    # 返回
    b.tap(*BTN_BACK)
    time.sleep(3.0)
    b.sudo("pkill -9 -f run_mc.py")

    out = b""
    for _ in range(6):
        try:
            while chan.recv_ready():
                out += chan.recv(65536)
        except Exception:
            break
        time.sleep(0.4)
    txt = out.decode("utf-8", "replace")
    print("\n---- MC 事件日志(尾部) ----")
    print(txt[-1500:])
    print("---- 判断 ----")
    print("  返回成功:", "MC RETURNED ok" in txt)
    print("  出现过 '放了一块':", txt.count("EV ('tap'") )

    b.sudo("rm -f /tmp/ui_tap; systemctl start zynq-desktop")
    b.close()


main()
