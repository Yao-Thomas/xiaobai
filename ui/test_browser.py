#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_browser.py —— 本地把真实网页抓下来渲染成 PNG (不需要板子)

用法: python test_browser.py [url] [输出名]
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
        self.img = Image.new("RGB", (self.w, self.h), (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)

    def flush(self, box=None):
        pass


fbui.Screen = FakeScreen

import webfetch as W          # noqa: E402
import htmlpage as HP         # noqa: E402


def render_page(scr, doc, yoff, url, title, msg=""):
    """极简浏览器外壳：顶栏 + 正文（只画可见部分）"""
    scr.clear((252, 252, 250))
    # 顶栏
    scr.rect([0, 0, scr.w, 56], fill=(38, 46, 66))
    fbui.btn(scr, [8, 8, 70, 48], "◀", fill=(64, 76, 104), size=22)
    fbui.btn(scr, [78, 8, 140, 48], "⟳", fill=(64, 76, 104), size=22)
    scr.text((152, 28), title[:46] or url, 20, (238, 244, 255), cn=True, anchor="lm")
    scr.rect([0, 54, scr.w, 58], fill=(86, 110, 160))
    # 正文
    n = 0
    last_lid = None
    cx = 0
    for it in doc.items:
        if it[0] == "text":
            _, x, y, t, sz, bd, ita, col, un, lid = it
            yy = y - yoff
            # ★ 按行顺序推进：行首用 layout 给的 x，之后逐个加【真实宽度】。
            #   靠估算宽度定位会漂移，导致词与词重叠或粘在一起。
            if lid != last_lid:
                cx = x
                last_lid = lid
            if t.strip() and 56 - sz * 1.7 <= yy <= scr.h:
                scr.text((cx, yy), t, sz, col, bold=bd, cn=True)
                if un:
                    scr.d.line([(cx, yy + int(sz * 1.24)),
                                (cx + int(scr.tw(t, sz, cn=True)), yy + int(sz * 1.24))],
                               fill=col, width=1)
                n += 1
            cx += int(scr.tw(t, sz, cn=True)) if t.strip() else int(scr.tw(" ", sz, cn=True))
        elif it[0] == "img":
            _, x, y, w, h, im = it
            yy = y - yoff
            if yy + h < 56 or yy > scr.h:
                continue
            try:
                scr.img.paste(im.resize((int(w), int(h))), (int(x), int(yy)))
                n += 1
            except Exception:
                pass
        elif it[0] == "rect":
            _, x, y, w, h, col = it
            yy = y - yoff
            if 56 <= yy <= scr.h:
                scr.d.rectangle([x, yy, x + w, yy + h], fill=col)
    if msg:
        scr.rect([0, scr.h - 34, scr.w, scr.h], fill=(40, 46, 62))
        scr.text((10, scr.h - 17), msg, 16, (255, 220, 160), cn=True, anchor="lm")
    return n


def main():
    url = W.norm_url(sys.argv[1] if len(sys.argv) > 1 else "http://example.com")
    name = sys.argv[2] if len(sys.argv) > 2 else "网页_预览.png"
    print("抓取:", url)
    t0 = time.time()
    r = W.fetch(url)
    t1 = time.time()
    print("  ok=%s ctype=%s len=%d err=%s  (%.0f ms)"
          % (r.ok, r.ctype[:30], len(r.data), r.err, (t1 - t0) * 1000))
    if not r.ok:
        return
    text = r.text()
    t0 = time.time()
    title, blocks = HP.parse_any(text, r.ctype, r.url, 18)
    t1 = time.time()
    print("  解析: %d 块  (%.0f ms)  title=%r" % (len(blocks), (t1 - t0) * 1000, title[:60]))

    scr = FakeScreen()
    doc = HP.Doc(title, url=r.url)

    # 图片抓取（限制大小，失败就算了）
    cache = {}

    def img_fetch(src):
        u = W.norm_url(src, r.url)
        if not u or u in cache:
            return cache.get(u)
        rr = W.fetch(u, timeout=10, max_bytes=400 * 1024)
        im = None
        if rr.ok and len(rr.data) > 100:
            try:
                im = Image.open(io.BytesIO(rr.data))
                im.load()
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGB")
            except Exception:
                im = None
        cache[u] = im
        return im

    doc.blocks = blocks
    t0 = time.time()
    HP.layout(scr, doc, 1024, pad=14, img_fetch=img_fetch)
    t1 = time.time()
    print("  排版: %d 绘制项 / %d 链接 / %d 图  高 %d px  (%.0f ms)"
          % (len(doc.items), len(doc.links), doc.n_img, doc.height, (t1 - t0) * 1000))

    render_page(scr, doc, 0, url, title)
    out = os.path.join(os.path.dirname(UI), "界面预览", name)
    scr.img.save(out)
    print("  ->", out)

    # 再出几张"往下滚"的
    for k, yoff in enumerate((400, 900)):
        render_page(scr, doc, yoff, url, title, "已滚动 %d px" % yoff)
        p2 = out.replace(".png", "_滚动%d.png" % (k + 1))
        scr.img.save(p2)
        print("  ->", p2)


main()
