#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_deploy.py —— 看桌面起没起来 + 补测脏区刷新耗时 + 抓屏"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot
from PIL import Image

IP = "192.168.10.18"
RAW = r"D:\ubuntu_iso\histrial\board_home.raw"
PNG = r"D:\ubuntu_iso\界面预览\真机_卡片首页.png"


def main():
    board.HOST = IP
    print("=" * 72)
    print("## 桌面服务状态 + 日志")
    broot.srun("systemctl is-active zynq-desktop zynq-screen-guard; echo '--- log ---'; "
               "tail -40 /var/log/zynq-desktop.log 2>/dev/null || "
               "journalctl -u zynq-desktop --no-pager -n 40", timeout=120)

    print("=" * 72)
    print("## 补测: 脏区刷新 / 纯时钟刷新")
    broot.srun("cd /home/zynq/uitest && python3 time_home.py", timeout=300)

    print("=" * 72)
    print("## 抓屏")
    broot.srun("dd if=/dev/fb0 of=/tmp/bh.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/bh.raw; ls -l /tmp/bh.raw", timeout=60)
    try:
        board.get("/tmp/bh.raw", RAW)
        d = open(RAW, "rb").read()
        Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072).save(PNG)
        print("-> " + PNG)
    except Exception as e:
        print("抓屏失败:", e)


main()
