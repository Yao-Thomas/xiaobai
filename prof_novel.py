#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prof_novel.py —— 部署新分页 + 用 cProfile 定位翻页慢在哪"""
import hashlib
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"
LOCAL = r"D:\ubuntu_iso\ui"
UIDIR = "/home/zynq/ui"

PERF = r'''
import sys, time, cProfile, pstats, io
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
for p, tag in (("/home/zynq/Books/03_大部头_性能测试_GBK.txt", "大部头 2.2MB"),
               ("/home/zynq/Books/01_项目进展报告_UTF8.txt", "中篇 110KB")):
    print("=== %s ===" % tag)
    t0 = time.time(); raw = open(p, "rb").read(); t1 = time.time()
    txt, enc = N._decode(raw); txt = N._norm(txt); t2 = time.time()
    cpl, lpp, lh = N.metrics(scr, 24)
    t3 = time.time(); starts = N.paginate(txt, cpl, lpp); t4 = time.time()
    print("  读文件 %.0fms | 解码 %.0fms | 分页 %.0fms | 共 %d 页 | %s"
          % ((t1-t0)*1000, (t2-t1)*1000, (t4-t3)*1000, len(starts), enc))
    r = N.Reader(p)
    t0 = time.time(); r.layout(scr); N.draw_reader(scr, r); t1 = time.time()
    print("  首屏 %.0fms" % ((t1-t0)*1000))
    t0 = time.time()
    for k in range(30):
        r.page = (r.page + 1) % max(1, r.npages() - 1)
        N.draw_reader(scr, r)
    t1 = time.time()
    print("  翻页 平均 %.1f ms/页" % ((t1-t0)*1000/30))

print("=== cProfile: draw_reader x30 ===")
r = N.Reader("/home/zynq/Books/01_项目进展报告_UTF8.txt")
r.layout(scr)
pr = cProfile.Profile(); pr.enable()
for k in range(30):
    r.page = (r.page + 1) % max(1, r.npages() - 1)
    N.draw_reader(scr, r)
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(14)
print(s.getvalue())
'''


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def main():
    board.HOST = IP
    for f in ("apps_novel.py", "fbui.py"):
        src = os.path.join(LOCAL, f)
        board.put(src, UIDIR + "/" + f)
        out, _ = board.run("md5sum %s/%s | cut -d' ' -f1" % (UIDIR, f), quiet=True, timeout=30)
        print("%-16s %s %s" % (f, "OK" if out.strip() == md5f(src) else "!!", out.strip()))
    open(r"D:\ubuntu_iso\prof_novel_src.py", "w", encoding="utf8").write(PERF)
    board.put(r"D:\ubuntu_iso\prof_novel_src.py", "/home/zynq/prof_novel.py")
    broot.srun("chown zynq:zynq %s/*.py /home/zynq/prof_novel.py" % UIDIR, quiet=True)
    broot.srun("cd /home/zynq && python3 prof_novel.py", timeout=900)


main()
