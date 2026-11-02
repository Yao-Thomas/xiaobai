#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mc_exit_test.py —— 前台跑 MC, 从另一条连接注入点击, 看它退不退出

不开 nohup / 后台, 免得进程归属和日志混淆。
"""
import sys
import threading
import time

sys.path.insert(0, ".")
from mc_lab import Board

SECS = 18
HITS = [
    ("快速点左上角返回按钮", 60, 30),
    ("点正中间(不该退出)", 512, 300),
    ("再点一次返回按钮", 60, 30),
]


def main():
    boss = Board()
    boss.sudo("systemctl stop zynq-desktop")
    boss.sudo("pkill -9 -f run_mc.py; rm -f /tmp/ui_tap")
    boss.sudo("pkill -9 -x python3")
    time.sleep(1.0)
    print("残留 python3 =", boss.run("pgrep -x python3 | wc -l").strip())

    # 前台启动(不读它的输出, 让它自己跑)
    chan = boss.c.get_transport().open_session()
    chan.exec_command(
        "cd /home/zynq/ui && exec sudo python3 run_mc.py %d --events 2>&1" % SECS)
    time.sleep(5.0)

    for label, x, y in HITS:
        alive = boss.run("pgrep -x python3 | wc -l").strip()
        print("\n[%s] 点 (%d,%d)  当前 python3=%s" % (label, x, y, alive))
        boss.tap(x, y)
        time.sleep(2.5)

    # 收全部输出
    out = b""
    try:
        while chan.recv_ready():
            out += chan.recv(65536)
    except Exception:
        pass
    time.sleep(0.5)
    try:
        while chan.recv_ready():
            out += chan.recv(65536)
    except Exception:
        pass
    txt = out.decode("utf-8", "replace")
    print("\n---- MC 输出 ----")
    print(txt[-3000:] if txt else "(空)")
    print("---- 结束 ----")
    print("MC RETURNED ok 出现:", "MC RETURNED ok" in txt)

    boss.sudo("pkill -9 -f run_mc.py; rm -f /tmp/ui_tap")
    boss.sudo("systemctl start zynq-desktop")
    boss.close()


main()
