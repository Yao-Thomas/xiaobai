#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_desktop.py —— 桌面点不进去的诊断"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot
from PIL import Image

IP = "192.168.10.18"
OUT = r"D:\ubuntu_iso\界面预览"

CMD = r'''
echo "### 桌面进程"
ps aux | grep -E "desktop.py|apps_" | grep -v grep
echo
echo "### 服务状态"
systemctl is-active zynq-desktop zynq-screen-guard
systemctl status zynq-desktop --no-pager 2>&1 | head -12
echo
echo "### 负载 / 内存"
uptime; free -m | head -3
echo
echo "### 触摸设备"
cat /proc/bus/input/devices | grep -E "Name=|Handlers=" | head -20
ls -l /dev/input/
echo
echo "### 桌面日志尾部 (去掉 WiFi 刷屏)"
tail -60 /var/log/zynq-desktop.log 2>/dev/null | strings | tail -30
'''


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    if not board.HOST:
        print("!! 板子网络不通")
        return
    broot.srun(CMD, timeout=180)

    print("### 抓屏")
    broot.srun("dd if=/dev/fb0 of=/tmp/bh.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/bh.raw", timeout=60, quiet=True)
    try:
        board.get("/tmp/bh.raw", r"D:\ubuntu_iso\histrial\_shot.raw")
        d = open(r"D:\ubuntu_iso\histrial\_shot.raw", "rb").read()
        Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072).save(
            os.path.join(OUT, "诊断_当前画面.png"))
        print("   -> 诊断_当前画面.png")
    except Exception as e:
        print("   抓屏失败", e)


main()
