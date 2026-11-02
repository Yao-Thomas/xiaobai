#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_home.py —— 最终验证: 日志无新异常 + 切页 + 抓屏 + 恢复黑屏守护"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot
from PIL import Image

IP = "192.168.10.18"
OUT = r"D:\ubuntu_iso\界面预览"


def shot(tag):
    broot.srun("dd if=/dev/fb0 of=/tmp/bh.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/bh.raw", timeout=60, quiet=True)
    local = r"D:\ubuntu_iso\histrial\_shot.raw"
    board.get("/tmp/bh.raw", local)
    d = open(local, "rb").read()
    im = Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072)
    p = os.path.join(OUT, tag)
    im.save(p)
    print("   -> " + p)
    return im


def main():
    board.HOST = IP
    print("## 本次启动以来的日志 (只取最近一次重启之后)")
    broot.srun("n=$(grep -n '卡片首页已加载' /var/log/zynq-desktop.log | tail -1 | cut -d: -f1); "
               "echo \"最后加载在第 $n 行\"; tail -n +$n /var/log/zynq-desktop.log | tail -25; "
               "echo '=== 有没有 Traceback ==='; "
               "tail -n +$n /var/log/zynq-desktop.log | grep -c Traceback", timeout=90)

    print("## 抓首页")
    shot("真机_卡片首页.png")

    print("## 点 Dock 的「应用」切到图标页 (注入一次 tap: 378,564)")
    broot.srun("printf '378,564' > /tmp/ui_tap", quiet=True)
    time.sleep(4)
    shot("真机_图标页.png")

    print("## 点「桌面」回首页 (注入 tap: 303,564)")
    broot.srun("printf '303,564' > /tmp/ui_tap", quiet=True)
    time.sleep(4)
    shot("真机_回首页.png")

    print("## 恢复黑屏守护")
    broot.srun("rm -f /home/zynq/.guard_pause; ls -l /home/zynq/.guard_pause 2>&1; "
               "systemctl is-active zynq-desktop zynq-screen-guard; "
               "systemctl --failed --no-pager", timeout=60)


main()
