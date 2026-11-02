#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_home.py —— 上板测 build_static 优化前后 + 验证壁纸切换会重建且能恢复"""
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
OUT = r"D:\ubuntu_iso\界面预览"


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def shot(tag):
    broot.srun("dd if=/dev/fb0 of=/tmp/bh.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/bh.raw", timeout=60, quiet=True)
    local = r"D:\ubuntu_iso\histrial\_shot.raw"
    board.get("/tmp/bh.raw", local)
    d = open(local, "rb").read()
    im = Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072)
    if tag:
        p = os.path.join(OUT, tag)
        im.save(p)
        print("   -> " + p)
    return im


def main():
    board.HOST = IP
    print("## 上传优化后的 home.py")
    src = os.path.join(LOCAL, "home.py")
    board.put(src, "/home/zynq/ui/home.py")
    out, _ = board.run("md5sum /home/zynq/ui/home.py | cut -d' ' -f1", quiet=True, timeout=30)
    print("   本地 %s" % md5f(src))
    print("   板上 %s  %s" % (out.strip(), "OK" if out.strip() == md5f(src) else "!!"))
    broot.srun("chown zynq:zynq /home/zynq/ui/*.py", quiet=True)

    print("## 上板测 build_static (共用玻璃后)")
    broot.srun("cp -f /home/zynq/ui/home.py /home/zynq/uitest/home.py; "
               "cp -f /home/zynq/ui/fbui.py /home/zynq/uitest/fbui.py", quiet=True)
    broot.srun("cd /home/zynq/uitest && python3 time_home.py", timeout=300)

    print("## 确认板上壁纸设置")
    broot.srun("ls -l /home/zynq/.wallpaper 2>&1; cat /home/zynq/.wallpaper 2>&1; "
               "ls -l $(cat /home/zynq/.wallpaper 2>/dev/null) 2>&1", timeout=60)

    print("## 重启桌面 (用新 home.py)")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 22; "
               "systemctl is-active zynq-desktop", timeout=180)
    shot("真机_首页_优化后.png")

    print("## 测壁纸切换: 记录当前 mtime, 然后 touch 触发重建")
    t0 = time.time()
    broot.srun("touch /home/zynq/.wallpaper", quiet=True)
    # 等它检测到 + 重建 + 画完
    time.sleep(6)
    print("   切换后等待 %.1fs" % (time.time() - t0))
    shot("真机_换壁纸后.png")

    print("## 日志复查")
    broot.srun("tail -12 /var/log/zynq-desktop.log | strings | tail -12; "
               "echo '=== 失败单元 ==='; systemctl --failed --no-pager", timeout=60)
    broot.srun("rm -f /home/zynq/.guard_pause")


main()
