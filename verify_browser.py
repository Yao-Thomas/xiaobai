#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_browser.py —— 重新部署 + 真机点链接验证"""
import hashlib
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot
from PIL import Image

IP = "192.168.10.18"
SRC = r"D:\ubuntu_iso\ui\apps_browser.py"
UIDIR = "/home/zynq/ui"
OUT = r"D:\ubuntu_iso\界面预览"


def shot(tag):
    broot.srun("dd if=/dev/fb0 of=/tmp/bh.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/bh.raw", timeout=60, quiet=True)
    local = r"D:\ubuntu_iso\histrial\_shot.raw"
    board.get("/tmp/bh.raw", local)
    d = open(local, "rb").read()
    Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072).save(
        os.path.join(OUT, tag))
    print("   -> " + tag)


def tap(x, y, w=2.0):
    broot.srun("printf '%d,%d' > /tmp/ui_tap" % (x, y), quiet=True)
    time.sleep(w)


def main():
    board.HOST = IP
    board.put(SRC, UIDIR + "/apps_browser.py")
    out, _ = board.run("md5sum %s/apps_browser.py | cut -d' ' -f1" % UIDIR,
                       quiet=True, timeout=30)
    print("apps_browser.py", "OK" if out.strip() == hashlib.md5(open(SRC, "rb").read()).hexdigest() else "!!")
    broot.srun("chown zynq:zynq %s/*.py" % UIDIR, quiet=True)
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 20",
               timeout=180)

    print("进浏览器")
    tap(556, 564, 4.0)
    shot("真机_P5_起始页.png")

    print("点起始页里的「必应搜索」链接 (约 200,235)")
    tap(200, 235, 8.0)
    shot("真机_P5_必应搜索.png")

    print("往下滚一点 (拖拽注入)")
    broot.srun("printf 'drag:500,420;500,300;500,200' > /tmp/ui_tap", quiet=True)
    time.sleep(3)
    shot("真机_P5_滚动.png")

    print("点第 2 条结果")
    tap(300, 240, 8.0)
    shot("真机_P5_点结果.png")

    print("日志")
    broot.srun("tail -60 /var/log/zynq-desktop.log | strings | tail -35", timeout=60)
    broot.srun("rm -f /home/zynq/.guard_pause")


main()
