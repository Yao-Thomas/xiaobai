#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_sites.py —— 一批候选站点的"能读出多少内容"对比"""
import io
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
UI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, UI)

from PIL import Image, ImageDraw
import fbui


class FS(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0
        self.gpu = None
        self.mode = "BGR;24"
        self._fast = True
        self.yoff = 0
        self.img = Image.new("RGB", (self.w, self.h), (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)

    def flush(self, box=None):
        pass


fbui.Screen = FS
import webfetch as W      # noqa: E402
import htmlpage as HP     # noqa: E402

URLS = [
    "https://www.bing.com/search?q=zynq+fpga&format=rss",
    "https://cn.bing.com/search?q=zynq+fpga&format=rss",
    "https://www.sogou.com/web?query=zynq+fpga",
    "https://m.baidu.com/s?wd=zynq+fpga",
    "https://www.baidu.com/s?wd=zynq+fpga",
    "https://search.bilibili.com/all?keyword=zynq",
    "https://www.zhihu.com/question/20794107",
    "https://so.csdn.net/so/search?q=zynq",
    "https://www.runoob.com/",
    "https://www.w3school.com.cn/",
    "https://en.wikipedia.org/wiki/Zynq",
    "https://zh.wikipedia.org/wiki/Zynq",
    "https://www.gcores.com/",
    "https://www.zhihu.com/",
    "https://news.qq.com/",
    "https://www.163.com/",
    "https://xw.qq.com/",
    "https://www.thepaper.cn/",
    "https://www.36kr.com/",
    "https://sspai.com/",
]

scr = FS()
for u in URLS:
    t0 = time.time()
    r = W.fetch(u, timeout=12)
    dt = (time.time() - t0) * 1000
    if not r.ok:
        print("%-56s FAIL %s" % (u[:56], r.err[:40]))
        continue
    txt = r.text()
    t0 = time.time()
    title, blocks = HP.parse(txt, 18, r.url)
    doc = HP.Doc(title, url=r.url)
    doc.blocks = blocks
    HP.layout(scr, doc, 1024, pad=14, img_fetch=None)
    pt = (time.time() - t0) * 1000
    # 正文可读字符数（粗略判断是不是 JS 空壳）
    chars = sum(len(it[3]) for it in doc.items if it[0] == "text")
    print("%-56s %6dKB %4d块 %5d项 %6d字 高%5d  %.0f/%.0fms"
          % (u[:56], len(r.data) // 1024, len(blocks), len(doc.items), chars,
             doc.height, dt, pt))
