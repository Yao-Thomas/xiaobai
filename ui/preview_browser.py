#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preview_browser.py —— 本地渲染浏览器界面 (不需要板子)

用法: python preview_browser.py [url ...]
"""
import io
import os
import sys
import time

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
        self.img = Image.new("RGB", (self.w, self.h), (250, 250, 248))
        self.d = ImageDraw.Draw(self.img)

    def flush(self, box=None):
        pass


class FakeTouch(object):
    def poll(self, move=False):
        return None


fbui.Screen = FakeScreen
OUT = os.path.join(os.path.dirname(UI), "界面预览")


def shot(b, name):
    b.draw()
    p = os.path.join(OUT, name)
    b.scr.img.save(p)
    print("   ->", name)
    return p


def main():
    import apps_browser as AB
    AB.fbui.Screen = FakeScreen
    scr = FakeScreen()
    b = AB.Browser(scr, FakeTouch())
    # 起始页
    b.go("about:home")
    shot(b, "浏览器_起始页.png")

    urls = sys.argv[1:] or [
        "https://www.bing.com/search?q=zynq%20fpga&format=rss",
        "https://text.npr.org/",
    ]
    for i, u in enumerate(urls):
        print("抓取:", u)
        t0 = time.time()
        b.go(u)
        # 等后台线程完成
        for _ in range(200):
            if b._take_result():
                break
            time.sleep(0.05)
        print("   %.1fs  高 %d px" % (time.time() - t0, b.doc.height if b.doc else 0))
        # 等图片
        for _ in range(40):
            if not b.loader.pending:
                break
            time.sleep(0.1)
        shot(b, "浏览器_%d页.png" % (i + 1))
        b.yoff = min(max(0, (b.doc.height or 0) - 540), 480)
        shot(b, "浏览器_%d页_滚动.png" % (i + 1))

    # 键盘输入态
    b.kb = fbui.MiniKeyboard(y0=322)
    b.input = "zynq fpga"
    shot(b, "浏览器_地址栏输入.png")


main()
