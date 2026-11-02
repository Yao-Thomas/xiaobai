#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_novel.py —— 本地测小说阅读器: 解码 / 分页 / 排版 / 出图 (不需要板子)"""
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, UI)

from PIL import Image, ImageDraw
import fbui


class FakeScreen(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0
        self.gpu = None
        self.mode = "BGR;24"
        self._fast = True
        self.yoff = 0
        self.img = Image.new("RGB", (self.w, self.h), (12, 16, 32))
        self.d = ImageDraw.Draw(self.img)

    def flush(self, box=None):
        pass


fbui.Screen = FakeScreen

SRC = r"D:\总文件夹\FPGA2026\比赛材料_项目进展报告.md"
GBK_SRC = r"D:\总文件夹\FPGA2026\板子上跑Minecraft_完整实验.md"
BOOKS = r"D:\ubuntu_iso\_books"
OUT = r"D:\ubuntu_iso\界面预览"


def make_samples():
    os.makedirs(BOOKS, exist_ok=True)
    # 1) UTF-8 样本: 用项目里的真实中文文档, 再加几章凑长一点
    t = open(SRC, encoding="utf8").read()
    body = []
    for ch in range(1, 6):
        body.append("\n\n第 %d 章  测试章节\n\n" % ch)
        body.append(t[:12000])
    txt = "".join(body)
    p1 = os.path.join(BOOKS, "项目进展报告_UTF8.txt")
    open(p1, "w", encoding="utf8").write(txt)

    # 2) GBK 样本: 验证最容易被忽视的编码分支
    t2 = open(GBK_SRC, encoding="utf8").read()
    p2 = os.path.join(BOOKS, "Minecraft实验_GBK.txt")
    open(p2, "wb").write(t2.encode("gbk", "ignore"))
    return p1, p2


def main():
    p1, p2 = make_samples()
    import apps_novel as N

    for p in (p1, p2):
        raw = open(p, "rb").read()
        txt, enc = N._decode(raw)
        txt = N._norm(txt)
        scr = FakeScreen()
        cpl, lpp, lh = N.metrics(scr, N.FONTS[2])
        starts = N.paginate(txt, cpl, lpp)
        bad = txt.count("\ufffd")
        print("%-30s %7.1f KB  编码=%-12s 每行%3d字 每屏%2d行  共 %d 页  替换字符=%d"
              % (os.path.basename(p), len(raw) / 1024.0, enc, cpl, lpp, len(starts), bad))

    # 渲染阅读器
    r = N.Reader(p1)
    scr = FakeScreen()
    r.layout(scr)
    r.theme = 1
    N.draw_reader(scr, r)
    o1 = os.path.join(OUT, "小说_阅读_米黄.png")
    scr.img.save(o1)
    print("-> " + o1)

    # 夜间主题 + 大字号
    r.theme = 2
    r.size = N.FONTS[4]
    r.layout(scr)
    N.draw_reader(scr, r)
    o2 = os.path.join(OUT, "小说_阅读_夜间大字号.png")
    scr.img.save(o2)
    print("-> " + o2)

    # 改字号后阅读位置有没有跑掉?
    r2 = N.Reader(p1)
    s2 = FakeScreen()
    r2.layout(s2)
    r2.page = 40
    off_before = r2.starts[r2.page]
    r2.size = N.FONTS[1]
    r2.layout(s2)
    off_after = r2.starts[r2.page]
    print("改字号前后页首偏移: %d -> %d  (差 %d 字, 应很小)"
          % (off_before, off_after, abs(off_after - off_before)))

    # 书架(空目录的样子)
    scr3 = FakeScreen()
    N.draw_shelf(scr3, [], {}, {}, 0)
    o3 = os.path.join(OUT, "小说_书架_空.png")
    scr3.img.save(o3)
    print("-> " + o3)


main()
