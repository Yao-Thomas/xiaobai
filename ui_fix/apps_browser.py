#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps_browser.py —— 板载简易浏览器

能力（写清楚，免得期待错）：
  · 抓 http/https（★ 板子上系统 CA 用不了，自动降级到不校验 —— 见 webfetch.py）
  · 极简 HTML/CSS 子集渲染（见 htmlpage.py），图文混排、链接可点
  · 搜索走 **必应的 RSS 输出**（`?format=rss`）：必应搜索页是 JS 渲染的，
    直接抓 HTML 什么都读不到；RSS 只有 5KB、1 秒内拿全、内容干净
  · 历史前进后退、刷新、书签（落盘 ~/.browser_marks.json）、起始页
  · 图片后台异步加载（当页只加载可见的，最多 24 张），解码失败画占位框

交互：
  · 点地址栏 -> 弹键盘输入（网址或关键词，关键词自动走搜索）
  · 上下拖动滚屏；右侧有 ▲▼ 和进度条
  · 点链接跳转；长按链接 = 加入书签
"""
import io
import os
import json
import time
import threading
import queue

from PIL import Image, ImageDraw

import fbui
import webfetch as W
import htmlpage as HP

TOP_H = 56
SB_W = 14                       # 右侧滚动条宽度
MARKS = "/home/zynq/.browser_marks.json"
HOME_URL = "about:home"
MAX_IMGS = 24
SEARCH = "https://www.bing.com/search?q=%s&format=rss"

# ---- 输入面板布局 ----
# ★ 2026-10-01: 原来只有输入框 + 迷你键盘；现在中间插了一行候选栏，
#   给中文拼音输入法显示候选字/词用，键盘相应压缩一点。
PANEL_Y = 240                                # 面板顶部
IN_Y0, IN_Y1 = 272, 306                      # 输入框
CAND_Y0, CAND_Y1 = 310, 344                  # ★ 候选栏
KB_Y = 350                                   # 键盘顶部
KB_KH = 42                                   # 键高
KB_GAP = 4                                   # 键间距
# 键盘 5 行 × (42+4) = 230 → 350..580，屏幕 600 放得下

# 候选栏上没有拼音时，显示几个常用搜索词（点一下直接搜）
QUICK_SEARCH = ["Zynq 教程", "今日新闻", "天气", "FPGA 入门", "百度", "知乎"]

BG = (250, 250, 248)
TOP_BG = (36, 44, 64)
BTN = (62, 74, 102)
BTN_HI = (86, 118, 180)
LINE = (214, 218, 226)

# 起始页（内置 HTML，不走网络）
HOME_HTML = """<html><head><title>起始页</title><style>
h1{font-size:30px;text-align:center;color:#1c2a44}
p{font-size:17px;color:#5a6478}
a{font-size:19px;color:#1c58c8}
</style></head><body>
<h1>Zynq 浏览器</h1>
<p>点上面的地址栏输入网址或关键词，回车即可。</p>
<p>下面这些站点实测能正常读（服务端渲染，不是 JS 空壳）：</p>
<p><a href="https://www.bing.com/search?q=zynq&format=rss">必应搜索（RSS 通道）</a></p>
<p><a href="https://www.163.com/">网易首页</a></p>
<p><a href="https://www.gcores.com/">机核 GCORES</a></p>
<p><a href="https://text.npr.org/">NPR (text.npr.org，极简英文新闻)</a></p>
<p><a href="https://www.cnblogs.com/">博客园</a></p>
<p><a href="http://example.com/">example.com</a></p>
<p><a href="about:marks">我的书签</a></p>
<p>注意：百度/知乎/腾讯新闻/必应结果页的正文都是 JS 渲染的，
这类页面用这个浏览器只能读到一点点内容 —— 不是坏了，是它们不给静态 HTML。</p>
</body></html>"""


# ===================== 图片异步加载 =====================
class ImgLoader(object):
    """后台抓图 + 缩放缓存。界面永远不因为图片卡住。"""

    def __init__(self):
        self.cache = {}          # src -> PIL.Image (已按需缩放) 或 None
        self.pending = set()
        self.q = queue.Queue(maxsize=64)
        self.n = 0
        t = threading.Thread(target=self._work, name="img", daemon=True)
        t.start()

    def _work(self):
        while True:
            src = self.q.get()
            if src is None:
                continue
            try:
                r = W.fetch(src, timeout=12, max_bytes=400 * 1024)
                im = None
                if r.ok and len(r.data) > 80:
                    im = Image.open(io.BytesIO(r.data))
                    im.load()
                    if im.mode not in ("RGB", "RGBA"):
                        im = im.convert("RGB")
                    elif im.mode == "RGBA":
                        im = im.convert("RGB")
                self.cache[src] = im
                if im is not None:
                    print("[browser] 图片 OK %s (%dx%d)" % (src[-40:], im.width, im.height))
            except Exception as e:
                self.cache[src] = None
            finally:
                self.pending.discard(src)

    def request(self, src, url_base=""):
        u = W.norm_url(src, url_base)
        if not u or u in self.cache or u in self.pending:
            return
        if self.n >= MAX_IMGS:
            self.cache[u] = None
            return
        self.n += 1
        self.pending.add(u)
        try:
            self.q.put_nowait(u)
        except queue.Full:
            pass

    def get(self, src, url_base=""):
        return self.cache.get(W.norm_url(src, url_base))

    def reset(self):
        self.cache.clear()
        self.pending.clear()
        self.n = 0


# ===================== 浏览器 =====================
class Browser(object):
    def __init__(self, scr, touch):
        self.scr = scr
        self.touch = touch
        self.loader = ImgLoader()
        self.hist = []           # [(url, title, blocks, yoff)]
        self.hpos = -1
        self.url = ""
        self.title = ""
        self.blocks = []
        self.doc = None
        self.yoff = 0
        self.msg = ""
        self.loading = False
        self.marks = self._load_marks()
        self.kb = None           # 键盘
        self.input = ""
        # ★ 2026-10-01: 本地中文拼音输入法（照搬 apps_agent.py 那套）
        #   原来浏览器只有 MiniKeyboard（0-9 a-z . _ - /），一个汉字都打不了，
        #   搜索中文只能靠语音。现在接了 ime_cn，拼音就能出汉字。
        self.ime = None
        try:
            from ime_cn import IME
            self.ime = IME()
        except Exception as e:
            print("[browser] IME 加载失败:", e, flush=True)
        self.py = ""             # 拼音缓冲（还没上屏的字母）
        self.cands = []          # 当前候选 [(文本, kind)]
        self.pinyin = True       # True=拼音模式 / False=英文模式
        self.press = None        # (x, y, yoff, t, url)
        self.result = None       # 后台抓取结果
        self._th = None

    # ---- 书签 ----
    def _load_marks(self):
        try:
            d = json.load(open(MARKS))
            return d if isinstance(d, list) else []
        except Exception:
            return []

    def _save_marks(self):
        try:
            json.dump(self.marks[:80], open(MARKS, "w"), ensure_ascii=False)
        except Exception:
            pass

    def toggle_mark(self):
        u = self.url
        if not u or u.startswith("about:"):
            self.msg = "这个页面不能加书签"
            return
        for i, m in enumerate(self.marks):
            if m[0] == u:
                self.marks.pop(i)
                self.msg = "已取消书签"
                self._save_marks()
                return
        self.marks.insert(0, [u, self.title or u])
        self.msg = "已加入书签 ★"
        self._save_marks()

    # ---- 抓取（后台线程）----
    def go(self, url, push=True, keep_scroll=False):
        raw = (url or "").strip()
        # ★ about: 要在 norm_url 之前判断，否则会被当成关键词丢给搜索引擎
        if raw == "about:home":
            self.url = HOME_URL
            self.title = "起始页"
            self.blocks = HP.parse(HOME_HTML, 18, HOME_URL)[1]
            self.msg = ""
            self._relayout()
            if push:
                self._push()
            return
        if raw == "about:marks":
            self._show_marks()
            if push:
                self._push()
            return
        if raw.startswith("about:"):
            return
        url = W.norm_url(raw, self.url if self.url else None)
        if not url:
            return
        self.loading = True
        self.msg = "正在打开 " + url[:70]
        self.result = None
        self._pending = (url, push)
        self._th = threading.Thread(target=self._fetch, args=(url,), daemon=True)
        self._th.start()

    def _fetch(self, url):
        r = W.fetch(url)
        self.result = (url, r)

    def _take_result(self):
        if self.result is None:
            return False
        url, r = self.result
        self.result = None
        self.loading = False
        if not r.ok:
            self.msg = "打开失败: %s" % r.err[:60]
            self.blocks = HP.parse(
                "<h2>打不开这个页面</h2><p>%s</p><p>%s</p>"
                "<p><a href='about:home'>回起始页</a></p>"
                % (url, r.err), 18, url)[1]
            self.title = "打开失败"
            self.url = url
            self._relayout()
            self._push()
            return True
        ctype = r.ctype.lower()
        data = r.data
        if ctype.startswith("image/"):
            try:
                im = Image.open(io.BytesIO(data))
                im.load()
                html = ("<html><head><title>%s</title></head><body>"
                        "<h3>图片 %dx%d</h3><img src='%s'>" % (url, im.width, im.height, url))
                self.title, self.blocks = url, HP.parse(html, 18, url)[1]
            except Exception as e:
                self.msg = "图片解码失败: %s" % e
                return True
        else:
            text = r.text()
            if len(data) > 2 * 1024 * 1024:
                self.msg = "页面很大 (%.1f MB)，可能不完整" % (len(data) / 1048576.0)
            self.title, self.blocks = HP.parse_any(text, r.ctype, r.url, 18)
        self.url = url
        self.loader.reset()
        self._relayout()
        self._push()
        return True

    def _relayout(self):
        self.doc = HP.Doc(self.title, url=self.url)
        self.doc.blocks = self.blocks
        t0 = time.time()
        HP.layout(self.scr, self.doc, 1024, pad=14, img_fetch=None)
        print("[browser] 排版 %d 项 / %d 链接 / 高 %d  (%.0f ms)"
              % (len(self.doc.items), len(self.doc.links), self.doc.height,
                 (time.time() - t0) * 1000))
        self.yoff = 0

    def _push(self):
        while len(self.hist) > self.hpos + 1:
            self.hist.pop()
        self.hist.append((self.url, self.title, self.blocks, 0))
        self.hpos = len(self.hist) - 1
        if len(self.hist) > 40:
            self.hist.pop(0)
            self.hpos -= 1

    def _show_marks(self):
        self.url = "about:marks"
        self.title = "我的书签"
        if not self.marks:
            body = "<h2>还没有书签</h2><p>在网页上点右上角的 ☆ 就能加。</p>"
        else:
            body = "<h2>我的书签</h2>"
            for u, t in self.marks:
                body += "<p><a href='%s'>%s</a></p><p style='font-size:13px;color:#6c7a90'>%s</p>" \
                        % (u, t or u, u)
        body += "<p><a href='about:home'>回起始页</a></p>"
        self.blocks = HP.parse(body, 18, "about:marks")[1]
        self._relayout()

    # ---- 导航操作 ----
    def back(self):
        if self.hpos > 0:
            self.hpos -= 1
            self._restore()
        else:
            self.msg = "没有上一页了"

    def forward(self):
        if self.hpos < len(self.hist) - 1:
            self.hpos += 1
            self._restore()
        else:
            self.msg = "没有下一页了"

    def _restore(self):
        url, title, blocks, yoff = self.hist[self.hpos]
        self.url, self.title, self.blocks = url, title, blocks
        self.loader.reset()
        self._relayout()
        self.msg = ""

    def reload(self):
        self.go(self.url, push=False)

    # ---- 绘制 ----
    def draw(self):
        scr = self.scr
        scr.clear(BG)
        vh = scr.h - TOP_H
        yoff = self.yoff
        # 正文
        drawn = 0
        last_lid = None
        cx = 0
        for it in self.doc.items:
            k = it[0]
            if k == "text":
                _, x, y, t, sz, bd, ita, col, un, lid = it
                yy = y - yoff + TOP_H
                if lid != last_lid:
                    cx = x
                    last_lid = lid
                if t.strip() and TOP_H - sz * 1.8 <= yy <= scr.h:
                    scr.text((cx, yy), t, sz, col, bold=bd, cn=True)
                    if un:
                        scr.d.line([(cx, yy + int(sz * 1.24)),
                                    (cx + int(scr.tw(t, sz, cn=True)), yy + int(sz * 1.24))],
                                   fill=col, width=1)
                    drawn += 1
                cx += int(scr.tw(t, sz, cn=True))
            elif k == "img" or k == "imgph":
                _, x, y, w, h, src = it
                yy = y - yoff + TOP_H
                if yy + h < TOP_H or yy > scr.h:
                    continue
                im = self.loader.get(src, self.url)
                if im is None:
                    self.loader.request(src, self.url)
                    scr.rrect([x, yy, x + w, yy + h], 6, fill=(232, 234, 238),
                              outline=(206, 210, 218), width=1)
                    scr.text((x + w // 2, yy + h // 2), "图片加载中…", 15,
                             (150, 156, 168), cn=True, anchor="mm")
                else:
                    try:
                        scr.img.paste(im.resize((int(w), int(h))), (int(x), int(yy)))
                        drawn += 1
                    except Exception:
                        pass
            elif k == "rect":
                _, x, y, w, h, col = it
                yy = y - yoff + TOP_H
                if TOP_H <= yy <= scr.h:
                    scr.d.rectangle([x, yy, x + w, yy + h], fill=col)
        # 右侧滚动条
        if self.doc.height > vh:
            scr.rect([1024 - SB_W, TOP_H, 1024, scr.h], fill=(238, 240, 244))
            bh = max(30, int(vh * vh / float(self.doc.height)))
            bt = TOP_H + int((vh - bh) * yoff / float(max(1, self.doc.height - vh)))
            scr.rrect([1024 - SB_W + 2, bt, 1024 - 2, bt + bh], 5, fill=(150, 162, 184))
        # 顶栏
        self._top_bar()
        # 提示条
        if self.msg:
            scr.rect([0, scr.h - 30, 1024, scr.h], fill=(46, 54, 74))
            scr.text((10, scr.h - 15), self.msg[:78], 15, (255, 226, 168),
                     cn=True, anchor="lm")
        if self.kb is not None:
            self._draw_input()

    def _top_bar(self):
        scr = self.scr
        scr.rect([0, 0, 1024, TOP_H], fill=TOP_BG)
        # ★ 最左边一个「桌面」按钮 —— 浏览器原来没有退出键，进去就出不来了。
        #   其它应用左上角都是"返回桌面"，这里保持一致。
        self.exit_btn = [8, 10, 66, TOP_H - 10]
        fbui.btn(scr, self.exit_btn, "桌面", fill=(150, 62, 70), size=16,
                 cn=True, radius=8)
        labels = [("◀", 74, 122), ("▶", 128, 176), ("⟳", 182, 230)]
        self._btns = []
        for t, x0, x1 in labels:
            # 用汉字/ASCII 代替特殊符号（那些字形字体里没有，会显示成方框）
            lab = {"◀": "后退", "▶": "前进", "⟳": "刷新"}[t]
            r = [x0, 10, x1, TOP_H - 10]
            self._btns.append((lab, r))
            fbui.btn(scr, r, lab, fill=BTN, size=16, cn=True, radius=8)
        # 地址栏
        self.addr = [240, 10, 900, TOP_H - 10]
        col = (30, 38, 58)
        scr.rrect(self.addr, 10, fill=col, outline=(96, 118, 160), width=2)
        u = self.url if self.url != HOME_URL else "about:home"
        if self.loading:
            u = "载入中… " + u
        scr.text((self.addr[0] + 12, (self.addr[1] + self.addr[3]) // 2), u[:70],
                 17, (226, 234, 248), cn=True, mono=False, anchor="lm")
        # 书签 + 主页/书签列表
        r = [904, 10, 958, TOP_H - 10]
        self._btns.append(("★", r))
        marked = any(m[0] == self.url for m in self.marks)
        # ★ 必须 cn=True —— 默认那个 DejaVu 字体里没有 ★ 字形，会显示成方框
        fbui.btn(scr, r, "★", fill=(196, 148, 40) if marked else BTN,
                 size=18, cn=True, radius=8)
        r2 = [962, 10, 1016, TOP_H - 10]
        self._btns.append(("≡", r2))
        fbui.btn(scr, r2, "≡", fill=BTN, size=18, cn=True, radius=8)
        scr.rect([0, TOP_H - 2, 1024, TOP_H], fill=(96, 118, 160))
        # 右下角翻页按钮
        self.pg = [("▲", [1024 - SB_W - 46, 70, 1024 - SB_W - 6, 116]),
                   ("▼", [1024 - SB_W - 46, 122, 1024 - SB_W - 6, 168]),
                   ("顶", [1024 - SB_W - 46, 174, 1024 - SB_W - 6, 220])]
        for t, rr in self.pg:
            fbui.btn(scr, rr, t, fill=(58, 70, 96), size=17, cn=True, radius=8)

    # ---- ★ 中文拼音输入法（2026-10-01 新增）----
    def refresh_cands(self):
        """重算候选列表"""
        if not self.pinyin:
            self.cands = []
            return
        if self.py and self.ime and getattr(self.ime, "ok", False):
            try:
                self.cands = self.ime.candidates(self.py, limit=8)
            except Exception:
                self.cands = []
        else:
            self.cands = []

    def commit(self, text):
        """把候选上屏，清掉拼音缓冲"""
        self.input += text
        self.py = ""
        self.refresh_cands()

    def commit_first(self):
        """空格/回车：有拼音就先上屏第一候选；没有候选就把字母原样上屏。

        返回 True 表示"吃掉"了这次按键（不要当普通空格/回车处理）。
        """
        if not self.py:
            return False
        if self.cands:
            self.commit(self.cands[0][0])
        else:
            self.input += self.py
            self.py = ""
            self.refresh_cands()
        return True

    def cand_items(self, scr):
        """候选栏上要画的东西 [(文本, 动作, 矩形)]"""
        items = []
        x = 22
        y0, y1 = CAND_Y0, CAND_Y1

        # 左侧：拼音/英文切换
        mw = 62
        items.append(("拼音" if self.pinyin else "英文", "mode",
                      [x, y0, x + mw, y1]))
        x += mw + 6

        if self.py and self.cands:
            for i, (t, kind) in enumerate(self.cands):
                try:
                    w = max(46, scr.tw(t, 20, cn=True) + 20)
                except Exception:
                    w = 46
                if x + w > 1006:
                    break
                items.append((t, "cand:%d" % i, [x, y0, x + w, y1]))
                x += w + 4
        elif self.py:
            items.append(("(无候选 → 回车原样上屏)", "none",
                          [x, y0, x + 266, y1]))
        else:
            # 没有拼音时给几个常用搜索词，点一下直接搜
            for i, q in enumerate(QUICK_SEARCH):
                try:
                    w = max(64, scr.tw(q, 17, cn=True) + 18)
                except Exception:
                    w = 64
                if x + w > 1006:
                    break
                items.append((q, "quick:%d" % i, [x, y0, x + w, y1]))
                x += w + 4
        return items

    def _draw_input(self):
        scr = self.scr
        # 面板：240..600
        scr.rect([0, PANEL_Y, 1024, scr.h], fill=(24, 30, 46))
        tip = ("输入网址或关键词，回车确认（拼音可打汉字）"
               if self.pinyin else "输入网址或关键词，回车确认"
               "（点上方空白处取消）")
        scr.text((20, 258), tip, 16, (150, 168, 200), cn=True, anchor="lm")

        # 输入框：已上屏的文字 + 正在打的拼音
        scr.rrect([16, IN_Y0, 1008, IN_Y1], 8, fill=(10, 14, 26),
                  outline=(90, 120, 180), width=2)
        shown = self.input
        if self.py:
            shown += "  [" + self.py + "]"
        scr.text((30, (IN_Y0 + IN_Y1) // 2), (shown or "")[-76:] + "_", 20,
                 (230, 240, 255), cn=True, anchor="lm")

        # ★ 候选栏
        for text, act, r in self.cand_items(scr):
            first = (act == "cand:0")
            fill = (52, 100, 150) if first else (40, 52, 78)
            fbui.btn(scr, r, text, fill=fill, size=18, cn=True, radius=6)

        self.kb.draw(scr)

    # ---- 事件 ----
    def tap(self, x, y):
        # 桌面 / 退出
        if fbui.hit(getattr(self, "exit_btn", [8, 10, 66, TOP_H - 10]), x, y):
            print("[browser] 点「桌面」退出")
            self.exit_now = True
            return
        # 键盘
        if self.kb is not None:
            # ① ★ 先看候选栏（拼音候选 / 模式切换 / 常用搜索词）
            for text, act, r in self.cand_items(self.scr):
                if not fbui.hit(r, x, y):
                    continue
                if act == "mode":
                    self.pinyin = not self.pinyin
                    if not self.pinyin and self.py:
                        # 切成英文：没上屏的拼音原样上屏
                        self.input += self.py
                        self.py = ""
                    self.refresh_cands()
                elif act.startswith("cand:"):
                    try:
                        i = int(act.split(":")[1])
                    except Exception:
                        i = -1
                    if 0 <= i < len(self.cands):
                        self.commit(self.cands[i][0])
                elif act.startswith("quick:"):
                    try:
                        i = int(act.split(":")[1])
                    except Exception:
                        i = -1
                    if 0 <= i < len(QUICK_SEARCH):
                        u = QUICK_SEARCH[i]
                        self.kb = None
                        self.input = ""
                        self.py = ""
                        self.refresh_cands()
                        self.go(u)
                return

            # ② 键盘本体
            c = self.kb.press(x, y)
            if c == "<BS>":
                if self.py:                  # ★ 优先退拼音
                    self.py = self.py[:-1]
                    self.refresh_cands()
                else:
                    self.input = self.input[:-1]
            elif c == "<ENTER>":
                # ★ 还有拼音没上屏 -> 先上屏第一候选，不跳出
                if self.commit_first():
                    return
                u = self.input.strip()
                self.kb = None
                self.input = ""
                self.py = ""
                self.refresh_cands()
                if u:
                    self.go(u)
            elif c == " ":
                # ★ 空格优先上屏候选；没有拼音才是真空格
                if not self.commit_first():
                    self.input += " "
            elif c:
                # ★ 拼音模式下字母进缓冲，不直接上屏
                if self.pinyin and c.isalpha():
                    self.py += c.lower()
                    self.refresh_cands()
                else:
                    self.input += c
            elif y < PANEL_Y:
                self.kb = None
                self.input = ""
                self.py = ""
                self.refresh_cands()
            return
        # 顶栏按钮
        for lab, r in getattr(self, "_btns", []):
            if fbui.hit(r, x, y):
                if lab == "后退":
                    self.back()
                elif lab == "前进":
                    self.forward()
                elif lab == "刷新":
                    self.reload()
                elif lab == "★":
                    self.toggle_mark()
                elif lab == "≡":
                    self._show_marks()
                return
        if fbui.hit(self.addr, x, y):
            # ★ 2026-10-01: 用新布局（压缩键盘 + 候选栏），并重置输入法状态
            self.kb = fbui.MiniKeyboard(y0=KB_Y, key_w=76, key_h=KB_KH,
                                        gap=KB_GAP)
            self.input = "" if self.url == HOME_URL else self.url
            self.py = ""
            self.pinyin = True
            self.refresh_cands()
            return
        for t, r in getattr(self, "pg", []):
            if fbui.hit(r, x, y):
                step = self.scr.h - TOP_H - 60
                if t == "▲":
                    self.yoff = max(0, self.yoff - step)
                elif t == "▼":
                    self.yoff = min(max(0, self.doc.height - (self.scr.h - TOP_H)),
                                    self.yoff + step)
                else:
                    self.yoff = 0
                return
        if y < TOP_H:
            return
        # 链接
        py = y - TOP_H + self.yoff
        for (x0, y0, x1, y1, u) in self.doc.links:
            if x0 - 2 <= x <= x1 + 2 and y0 <= py <= y1:
                print("[browser] 点链接", u)
                self.msg = "打开 " + u[:70]
                self.go(u)
                return

    def scroll(self, dy):
        mx = max(0, self.doc.height - (self.scr.h - TOP_H))
        self.yoff = max(0, min(mx, self.yoff + dy))

    def run(self):
        self.go(HOME_URL)
        # ★ 必须先画一帧：tap() 里用到的 self.addr / self._btns / self.pg
        #   都是 _top_bar() 里建的，没画过就点会 AttributeError。
        self.draw()
        self.scr.flush()
        print("[browser] 已启动")
        self.exit_now = False
        last = 0
        while True:
            changed = False
            if self._take_result():
                changed = True
            # 图片陆续到货 -> 重画
            if self.loader.cache and time.time() - last > 0.4:
                last = time.time()
                changed = True
            if changed:
                self.draw()
                self.scr.flush()
            ev = self.touch.poll(move=True)
            if not ev:
                if self.exit_now:
                    return
                time.sleep(0.03)
                continue
            k, x, y = ev
            if k == "down":
                self.press = (x, y, self.yoff, time.time())
                self._last_y = y
                self.dragging = False
                continue
            if k == "move":
                if self.press and self.kb is None:
                    dy_total = y - self.press[1]
                    if abs(dy_total) > 10:
                        self.dragging = True
                    if self.dragging:
                        dy = y - getattr(self, "_last_y", y)
                        self._last_y = y
                        self.scroll(-dy)
                        self.draw()
                        self.scr.flush()
                self._last_y = y
                continue
            if k == "up":
                if self.press and not self.dragging:
                    self.tap(x, y)
                    # ★ 2026-10-01: 点完必须重画一次。
                    #   主循环原来只在 _take_result / 图片到货 时才 draw()，
                    #   而 tap() 改了状态（比如弹出输入键盘）根本不会触发重画
                    #   —— 表现就是"点了地址栏没反应"（其实 self.kb 已经设上了，
                    #   只是没画出来）。
                    self.draw()
                    self.scr.flush()
                self.press = None
                self.dragging = False
                if self.exit_now:
                    return
                continue
            # 注入的 tap
            self.tap(x, y)
            self.draw()                 # ★ 同上：点完立刻重画
            self.scr.flush()
            if self.exit_now:
                return


def run(scr, touch):
    b = Browser(scr, touch)
    b.run()
