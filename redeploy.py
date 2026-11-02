#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redeploy.py —— 重新上传 home.py/desktop.py, 重启桌面, 验证脏区刷新不再崩"""
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
LOCAL = r"D:\ubuntu_iso\ui"
UIDIR = "/home/zynq/ui"
PNG = r"D:\ubuntu_iso\界面预览\真机_卡片首页.png"
PNG2 = r"D:\ubuntu_iso\界面预览\真机_图标页.png"


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def shot(remote="/tmp/bh.raw"):
    broot.srun("dd if=/dev/fb0 of=%s bs=1M count=2 2>/dev/null; chmod 644 %s" % (remote, remote),
               timeout=60, quiet=True)
    local = r"D:\ubuntu_iso\histrial\_shot.raw"
    board.get(remote, local)
    d = open(local, "rb").read()
    return Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072)


def main():
    board.HOST = IP
    print("## 上传")
    for f in ("home.py", "desktop.py"):
        board.put(os.path.join(LOCAL, f), UIDIR + "/" + f)
        out, _ = board.run("md5sum %s/%s | cut -d' ' -f1" % (UIDIR, f), quiet=True, timeout=30)
        print("   %-12s %s %s" % (f, "OK" if out.strip() == md5f(os.path.join(LOCAL, f)) else "!!",
                                  out.strip()))
    broot.srun("chown zynq:zynq %s/*.py" % UIDIR, quiet=True)

    print("## 先测脏区刷新 (假屏幕)")
    broot.srun("rm -rf /home/zynq/uitest && mkdir -p /home/zynq/uitest && "
               "chown zynq:zynq /home/zynq/uitest", quiet=True)
    for f in ("fbui.py", "home.py", "time_home.py"):
        board.put(os.path.join(LOCAL, f), "/home/zynq/uitest/" + f)
    broot.srun("cd /home/zynq/uitest && python3 time_home.py", timeout=300)

    print("## 重启桌面")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 25; "
               "systemctl is-active zynq-desktop; echo '--- log tail ---'; "
               "tail -25 /var/log/zynq-desktop.log", timeout=180)

    print("## 抓屏 (首页)")
    im = shot()
    im.save(PNG)
    print("   -> " + PNG)

    print("## 切到图标页再抓一张")
    broot.srun("echo 'down:60,60' > /tmp/ui_tap; sleep 1; "
               "rm -f /tmp/ui_tap", quiet=True, timeout=30)
    time.sleep(3)
    im2 = shot()
    im2.save(PNG2)
    print("   -> " + PNG2)

    print("## 日志复查 (应无 Traceback)")
    broot.srun("tail -20 /var/log/zynq-desktop.log; echo '=== 失败单元 ==='; "
               "systemctl --failed --no-pager", timeout=60)


main()
