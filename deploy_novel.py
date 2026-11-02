#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_novel.py —— 部署小说阅读器并真机验证 (书架 + 阅读 + 翻页 + 书签 + 字号)"""
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


def tap(x, y, wait=2.0):
    broot.srun("printf '%d,%d' > /tmp/ui_tap" % (x, y), quiet=True)
    time.sleep(wait)


def main():
    board.HOST = IP
    print("## 上传")
    for f in ("apps_novel.py", "fbui.py", "desktop.py"):
        src = os.path.join(LOCAL, f)
        board.put(src, UIDIR + "/" + f)
        out, _ = board.run("md5sum %s/%s | cut -d' ' -f1" % (UIDIR, f), quiet=True, timeout=30)
        print("   %-16s %s" % (f, "OK" if out.strip() == md5f(src) else "!!"))
    broot.srun("chown zynq:zynq %s/*.py" % UIDIR, quiet=True)

    print("## 重启桌面")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 20",
               timeout=180)

    print("## 点 Dock「小说」进书架")
    tap(468, 564, 3.0)
    shot("真机_P3_书架.png", wait=1)

    print("## 打开第 1 本书 (小本)")
    tap(400, 112, 3.5)
    shot("真机_P3_阅读器.png", wait=1)

    print("## 翻 3 页")
    for _ in range(3):
        tap(860, 300, 1.2)
    shot("真机_P3_翻页后.png", wait=1)

    print("## 加书签 + 切主题")
    tap(706, 562, 1.5)      # 书签
    tap(890, 562, 1.5)      # 主题
    shot("真机_P3_书签与主题.png", wait=1)

    print("## 返回书架, 打开大本 (2.2MB, 测排版耗时)")
    tap(65, 30, 2.5)        # 返回
    t0 = time.time()
    tap(400, 190, 6.0)      # 第 3 行 -> 大部头
    print("   等了 %.1fs" % (time.time() - t0))
    shot("真机_P3_大部头.png", wait=1)

    print("## 日志")
    broot.srun("tail -40 /var/log/zynq-desktop.log | strings | tail -25", timeout=60)
    broot.srun("echo '=== 进度文件 ==='; cat /home/zynq/.novel_pos.json; echo; "
               "echo '=== 书签 ==='; cat /home/zynq/.novel_marks.json; echo", timeout=60)
    broot.srun("rm -f /home/zynq/.guard_pause")


main()
