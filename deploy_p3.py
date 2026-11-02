#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_p3.py —— 部署小说阅读器 + 造样本书 + 上板测分页性能 + 抓图"""
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
BOOKS = r"D:\ubuntu_iso\_books"
OUT = r"D:\ubuntu_iso\界面预览"
SRC = r"D:\总文件夹\FPGA2026\比赛材料_项目进展报告.md"
SRC2 = r"D:\总文件夹\FPGA2026\板子上跑Minecraft_完整实验.md"
SRC3 = r"D:\总文件夹\FPGA2026\使用手册.md"

PERF = r'''
import sys, time
sys.path.insert(0, "/home/zynq/ui")
from PIL import Image, ImageDraw
import fbui
class FS(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0; self.gpu = None; self.mode = "BGR;24"
        self._fast = True; self.yoff = 0
        self.img = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
    def flush(self, box=None): pass
fbui.Screen = FS
import apps_novel as N
scr = FS()
p = sys.argv[1]
t0 = time.time(); raw = open(p, "rb").read(); t1 = time.time()
txt, enc = N._decode(raw); txt = N._norm(txt); t2 = time.time()
cpl, lpp, lh = N.metrics(scr, 24)
t3 = time.time(); starts = N.paginate(txt, cpl, lpp); t4 = time.time()
print("  读文件 %.0fms | 解码 %.0fms | 分页 %.0fms | 共 %d 页 | 编码 %s"
      % ((t1-t0)*1000, (t2-t1)*1000, (t4-t3)*1000, len(starts), enc))
r = N.Reader(p)
t0 = time.time(); r.layout(scr); N.draw_reader(scr, r); t1 = time.time()
print("  首屏渲染 %.0fms" % ((t1-t0)*1000))
t0 = time.time()
for k in range(20):
    r.page += 1
    N.draw_reader(scr, r)
t1 = time.time()
print("  翻页 平均 %.1f ms/页" % ((t1-t0)*1000/20))
'''


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def make_books():
    os.makedirs(BOOKS, exist_ok=True)
    t = open(SRC, encoding="utf8").read()
    t2 = open(SRC2, encoding="utf8").read()
    t3 = open(SRC3, encoding="utf8").read()
    # 1) UTF-8
    body = []
    for ch in range(1, 6):
        body.append("\n\n第 %d 章  测试章节\n\n" % ch)
        body.append(t[:12000])
    open(os.path.join(BOOKS, "01_项目进展报告_UTF8.txt"), "w",
         encoding="utf8").write("".join(body))
    # 2) GBK（中文小说最常见的编码）
    open(os.path.join(BOOKS, "02_Minecraft实验_GBK.txt"), "wb").write(
        t2.encode("gbk", "ignore"))
    # 3) 大文件，专测分页性能（约 1.2MB）
    big = []
    for k in range(40):
        big.append("\n\n第 %d 卷  开始\n\n" % (k + 1))
        big.append(t + t2 + t3)
    data = "".join(big)
    open(os.path.join(BOOKS, "03_大部头_性能测试_GBK.txt"), "wb").write(
        data.encode("gbk", "ignore"))
    for f in sorted(os.listdir(BOOKS)):
        print("   %-34s %8.1f KB" % (f, os.path.getsize(os.path.join(BOOKS, f)) / 1024.0))


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


def tap(x, y, wait=2.5):
    broot.srun("printf '%d,%d' > /tmp/ui_tap" % (x, y), quiet=True)
    time.sleep(wait)


def main():
    board.HOST = IP

    print("## 造样本书")
    make_books()

    print("## 上传样本到 /home/zynq/Books")
    broot.srun("mkdir -p /home/zynq/Books && chown zynq:zynq /home/zynq/Books", quiet=True)
    for f in sorted(os.listdir(BOOKS)):
        board.put(os.path.join(BOOKS, f), "/home/zynq/Books/" + f)
    broot.srun("chown zynq:zynq /home/zynq/Books/*; ls -l /home/zynq/Books/", timeout=60)

    print("## 上传代码")
    open(r"D:\ubuntu_iso\perf_novel.py", "w", encoding="utf8").write(PERF)
    for f in ("apps_novel.py", "desktop.py"):
        src = os.path.join(LOCAL, f)
        board.put(src, UIDIR + "/" + f)
        out, _ = board.run("md5sum %s/%s | cut -d' ' -f1" % (UIDIR, f), quiet=True, timeout=30)
        print("   %-16s %s %s" % (f, "OK" if out.strip() == md5f(src) else "!!", out.strip()))
    board.put(r"D:\ubuntu_iso\perf_novel.py", "/home/zynq/perf_novel.py")
    broot.srun("chown zynq:zynq %s/*.py /home/zynq/perf_novel.py" % UIDIR, quiet=True)

    print("## 上板测分页/渲染性能 (假屏幕)")
    broot.srun("cd /home/zynq && python3 perf_novel.py '/home/zynq/Books/03_大部头_性能测试_GBK.txt'",
               timeout=600)
    broot.srun("cd /home/zynq && python3 perf_novel.py '/home/zynq/Books/02_Minecraft实验_GBK.txt'",
               timeout=300)

    print("## 重启桌面, 打开小说")
    broot.srun("touch /home/zynq/.guard_pause; systemctl restart zynq-desktop; sleep 18",
               timeout=180)
    tap(468, 564)          # Dock 的「小说」
    tap(0, 0, 1.5)
    shot("真机_P3_书架.png", wait=2)

    print("## 打开第一本书")
    tap(400, 110, 3.0)
    shot("真机_P3_阅读器.png", wait=2)

    print("## 日志")
    broot.srun("tail -30 /var/log/zynq-desktop.log | strings | tail -20", timeout=60)
    broot.srun("rm -f /home/zynq/.guard_pause")


main()
