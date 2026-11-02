#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_browser.py —— P5 上板验证：部署 + 真机抓图 + 看 TLS 降级到哪一级"""
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
OUT = r"D:\ubuntu_iso\界面预览"


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def shot(tag, wait=0):
    if wait:
        time.sleep(wait)
    broot.srun("dd if=/dev/fb0 of=/tmp/bh.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/bh.raw", timeout=60, quiet=True)
    local = r"D:\ubuntu_iso\histrial\_shot.raw"
    board.get("/tmp/bh.raw", local)
    d = open(local, "rb").read()
    im = Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072)
    im.save(os.path.join(OUT, tag))
    print("   -> " + tag)


def tap(x, y, wait=2.0):
    broot.srun("printf '%d,%d' > /tmp/ui_tap" % (x, y), quiet=True)
    time.sleep(wait)


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    if not board.HOST:
        return

    print("## 上传")
    for f in ("webfetch.py", "htmlpage.py", "apps_browser.py", "desktop.py",
              "fbui.py"):
        src = os.path.join(LOCAL, f)
        board.put(src, UIDIR + "/" + f)
        out, _ = board.run("md5sum %s/%s | cut -d' ' -f1" % (UIDIR, f),
                           quiet=True, timeout=30)
        print("   %-18s %s" % (f, "OK" if out.strip() == md5f(src) else "!!"))
    broot.srun("chown zynq:zynq %s/*.py" % UIDIR, quiet=True)

    print("## 先在板子上直接测抓取 (看 TLS 降级到哪一级)")
    broot.srun("cd %s && python3 webfetch.py "
               "'https://text.npr.org/' "
               "'https://www.bing.com/search?q=zynq+fpga&format=rss' "
               "'http://example.com' 2>&1 | head -20" % UIDIR, timeout=300)

    print("## 重启桌面")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 20",
               timeout=180)

    print("## 点 Dock「浏览器」(556,564)")
    tap(556, 564, 4.0)
    shot("真机_P5_起始页.png")

    print("## 点地址栏 -> 弹键盘")
    tap(500, 36, 2.0)
    shot("真机_P5_键盘.png")

    print("## 输入必应搜索 (用注入的方式直接导航更稳): 先关键盘")
    tap(500, 200, 1.5)      # 点上方空白关掉键盘
    shot("真机_P5_关键盘.png")

    print("## 直接测导航: 注入 tap 点到起始页里的「必应搜索」链接")
    tap(200, 235, 6.0)
    shot("真机_P5_必应搜索.png")

    print("## 日志")
    broot.srun("tail -40 /var/log/zynq-desktop.log | strings | tail -30", timeout=60)
    broot.srun("rm -f /home/zynq/.guard_pause")


main()
