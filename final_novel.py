#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_novel.py —— 部署修复后的阅读器 + 清理重复样本 + 重新抓图"""
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
SRC = r"D:\ubuntu_iso\ui\apps_novel.py"
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
    board.put(SRC, "/home/zynq/ui/apps_novel.py")
    out, _ = board.run("md5sum /home/zynq/ui/apps_novel.py | cut -d' ' -f1",
                       quiet=True, timeout=30)
    ok = out.strip() == hashlib.md5(open(SRC, "rb").read()).hexdigest()
    print("apps_novel.py %s" % ("OK" if ok else "!!"))

    print("清掉重复样本")
    broot.srun("cd /home/zynq/Books && rm -f 'Minecraft实验_GBK.txt' "
               "'项目进展报告_UTF8.txt' && ls -l", timeout=60)
    broot.srun("chown zynq:zynq /home/zynq/ui/*.py", quiet=True)

    print("重启桌面")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 20",
               timeout=180)

    print("进书架")
    tap(468, 564, 3.0)
    shot("真机_P3_书架.png")

    print("打开第 1 本, 往后翻 6 页 (看混排行会不会被切)")
    tap(400, 112, 3.5)
    for _ in range(6):
        tap(860, 300, 1.0)
    shot("真机_P3_阅读器.png")

    print("切米黄主题")
    tap(890, 562, 2.0)
    shot("真机_P3_米黄主题.png")

    broot.srun("rm -f /home/zynq/.guard_pause; systemctl is-active zynq-desktop; "
               "cat /home/zynq/.novel_pos.json; echo", timeout=60)


main()
