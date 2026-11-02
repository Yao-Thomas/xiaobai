#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_p2.py —— 部署 P2(天气 + 信号强度), 并在板子上验证真实数据"""
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
    p = os.path.join(OUT, tag)
    im.save(p)
    print("   -> " + p)
    return im


def main():
    board.HOST = IP

    print("## 先在板子上单独跑一次 weather.py (确认取数真的通)")
    for f in ("weather.py",):
        board.put(os.path.join(LOCAL, f), UIDIR + "/" + f)
    broot.srun("chown zynq:zynq %s/*.py; cd %s && python3 weather.py" % (UIDIR, UIDIR),
               timeout=180)

    print("## 上传 home.py")
    board.put(os.path.join(LOCAL, "home.py"), UIDIR + "/home.py")
    out, _ = board.run("md5sum %s/home.py | cut -d' ' -f1" % UIDIR, quiet=True, timeout=30)
    ok = out.strip() == md5f(os.path.join(LOCAL, "home.py"))
    print("   home.py %s %s" % ("OK" if ok else "!!", out.strip()))
    broot.srun("chown zynq:zynq %s/*.py" % UIDIR, quiet=True)

    print("## 重启桌面, 等天气抓回来")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 12",
               timeout=180)
    shot("真机_P2_天气.png", wait=15)

    print("## 日志")
    broot.srun("tail -20 /var/log/zynq-desktop.log | strings | tail -20; "
               "echo '=== weather 缓存 ==='; cat /home/zynq/.weather.json; echo; "
               "echo '=== 失败单元 ==='; systemctl --failed --no-pager", timeout=60)
    broot.srun("rm -f /home/zynq/.guard_pause")


main()
