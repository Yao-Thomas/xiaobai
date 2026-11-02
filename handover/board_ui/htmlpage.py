#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
htmlpage.py —— 极简 HTML/CSS 子集解析 + 排版（给板载简易浏览器用）

为什么自己写：
  A9 667MHz + 无 GPU，WebKit/Gecko 想都不用想。这里只做"能读懂图文页面"这件事。

能力边界（写清楚，免得期待错）：
  · 块级：div p h1~h6 li ul ol br hr pre blockquote section article header footer
          nav aside table tr td th center main figure figcaption form
  · 行内：a b strong i em u code small big font span sup sub
  · 直接丢掉：script style(另抓) iframe svg canvas video audio select input textarea noscript
  · CSS：标签选择器 / .class / #id / 内联 style；属性支持
          color background-color font-size font-weight text-align margin(-top/bottom)
          padding border display:none line-height
  · 图片：<img src> 会真的去抓（限制大小 400KB，失败就画个占位框）
  · 表格：按"每个单元格一行"的极简方式排（不做真正的网格）
  · 不做：JS、浮动、绝对定位、flex/grid、伪元素
"""
import os
import re
import html as _html
from html.parser import HTMLParser
from urllib.parse import urljoin

# ---- 颜色 ----
NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (220, 40, 40),
    "green": (30, 140, 60), "blue": (40, 90, 220), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "yellow": (230, 210, 40),
    "orange": (235, 140, 30), "purple": (140, 70, 200), "navy": (20, 40, 110),
    "teal": (20, 130, 130), "maroon": (130, 30, 30), "olive": (120, 120, 30),
    "lime": (60, 200, 60), "aqua": (60, 200, 200), "fuchsia": (220, 60, 200),
    "darkgray": (80, 80, 80), "lightgray": (215, 215, 215),
}


def parse_color(v):
    if not v:
        return None
    v = v.strip().lower()
    if v in ("transparent", "inherit", "initial", "none"):
        return None
    if v.startswith("#"):
        h = v[1:]
        try:
            if len(h) == 3:
                return tuple(int(c * 2, 16) for c in h)
            if len(h) == 6:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None
    m = re.match(r"rgba?\(([^)]+)\)", v)
    if m:
        p = [x.strip() for x in m.group(1).replace("/", " ").split(",")]
        try:
            return (int(float(p[0])), int(float(p[1])), int(float(p[2])))
        except Exception:
            return None
    return NAMED.get(v)


# ---- 标签分类 ----
BLOCK = set("""div p h1 h2 h3 h4 h5 h6 li ul ol br hr pre blockquote section article
header footer nav aside table tr td th center main figure figcaption form dl dt dd
address fieldset legend caption details summary""".split())
SKIP = set("""script style noscript iframe svg canvas video audio select option input
textarea button object embed map area template""".split())
HEAD_SIZE = {"h1": 34, "h2": 29, "h3": 25, "h4": 22, "h5": 20, "h6": 18}


def _fs(v, base):
    """font-size: 支持 px / pt / em / % / 关键字"""
    if not v:
        return None
    v = v.strip().lower()
    kw = {"xx-small": 0.6, "x-small": 0.7, "small": 0.85, "medium": 1.0,
          "large": 1.15, "x-large": 1.3, "xx-large": 1.5}
    if v in kw:
        return int(base * kw[v])
    m = re.match(r"([\d.]+)\s*(px|pt|em|rem|%)?", v)
    if not m:
        return None
    n = float(m.group(1))
    u = m.group(2) or "px"
    if u == "pt":
        n = n * 96.0 / 72.0
    elif u in ("em", "rem"):
        n = n * base
    elif u == "%":
        n = n / 100.0 * base
    return max(8, min(72, int(n)))


def _mlen(v):
    if not v:
        return None
    m = re.match(r"(-?[\d.]+)\s*(px|pt|em)?", v.strip())
    if not m:
        return 0 if v.strip() in ("0", "auto") else None
    n = float(m.group(1))
    u = m.group(2) or "px"
    if u == "pt":
        n = n * 96.0 / 72.0
    elif u == "em":
        n = n * 16
    return int(n)


def parse_style(txt, base_size):
    """把 'a:b; c:d' 解成 dict（只认我们支持的属性）"""
    out = {}
    if not txt:
        return out
    for part in txt.split(";"):
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        k = k.strip().lower()
        v = v.strip()
        if not v or "url(" in v.lower():
            continue
        if k == "color":
            c = parse_color(v)
            if c:
                out["color"] = c
        elif k in ("background", "background-color"):
            c = parse_color(v)
            if c:
                out["bg"] = c
        elif k in ("font-size",):
            s = _fs(v, base_size)
            if s:
                out["size"] = s
        elif k in ("font-weight",):
            out["bold"] = (v in ("bold", "bolder") or
                           (v.isdigit() and int(v) >= 600))
        elif k in ("font-style",):
            out["italic"] = (v == "italic")
        elif k in ("text-align",):
            if v in ("left", "right", "center", "justify"):
                out["align"] = v
        elif k == "margin":
            p = v.split()
            if p:
                m = _mlen(p[0])
                if m is not None:
                    out["mt"] = m
                if len(p) > 2:
                    m2 = _mlen(p[2])
                    if m2 is not None:
                        out["mb"] = m2
        elif k == "margin-top":
            m = _mlen(v)
            if m is not None:
                out["mt"] = m
        elif k == "margin-bottom":
            m = _mlen(v)
            if m is not None:
                out["mb"] = m
        elif k == "padding":
            pass
        elif k == "line-height":
            m = _mlen(v)
            if m:
                out["lh"] = max(1.0, min(3.0, m / float(base_size or 16)))
        elif k == "display":
            if v == "none":
                out["hide"] = True
        elif k in ("text-decoration",) and "underline" in v:
            out["underline"] = True
    return out


class CSS(object):
    """极简 CSS：支持 tag / .class / #id，后者覆盖前者（不做权重计算）"""

    def __init__(self, base=18):
        self.base = base
        self.rules = []          # [(kind, key, props)]

    def add(self, text):
        text = re.sub(r"/\*.*?\*/", "", text or "", flags=re.S)
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            sels, body = m.group(1), m.group(2)
            props = parse_style(body, self.base)
            if not props:
                continue
            for sel in sels.split(","):
                sel = sel.strip()
                if not sel or any(c in sel for c in " >+~[]:("):
                    continue
                if sel.startswith("."):
                    self.rules.append(("class", sel[1:].lower(), props))
                elif sel.startswith("#"):
                    self.rules.append(("id", sel[1:].lower(), props))
                elif re.match(r"^[a-zA-Z][\w-]*$", sel):
                    self.rules.append(("tag", sel.lower(), props))

    def match(self, tag, cls, eid):
        out = {}
        for kind, key, props in self.rules:
            if ((kind == "tag" and key == tag) or
                    (kind == "class" and key in cls) or
                    (kind == "id" and key == eid)):
                out.update(props)
        return out


# ---- 块 ----
class Blk(object):
    __slots__ = ("tag", "size", "bold", "italic", "color", "bg", "align",
                 "runs", "mt", "mb", "is_img", "url", "pre", "lh", "hide",
                 "img_src", "img_w", "img_h", "indent", "bullet")

    def __init__(self, tag="p"):
        self.tag = tag
        self.size = 18
        self.bold = False
        self.italic = False
        self.color = (28, 30, 36)
        self.bg = None
        self.align = "left"
        self.runs = []          # [(text, {style})]
        self.mt = 6
        self.mb = 6
        self.is_img = False
        self.img_src = ""
        self.img_w = self.img_h = 0
        self.url = ""
        self.pre = False
        self.lh = 1.32
        self.hide = False
        self.indent = 0
        self.bullet = ""


class _P(HTMLParser):
    def __init__(self, css, base=18, base_url=""):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.css = css
        self.base = base
        self.base_url = base_url
        self.blocks = []
        self.stack = []          # [(tag, cls, eid, stylestack)]
        self.cur = None
        self.cur_style = {}
        self.skip_stack = []     # 用栈而不是计数器: <style> 的内容要单独收集
        self._stylebuf = []
        self.in_pre = 0
        self.ol_stack = []
        self.title = ""
        self.in_title = False
        self.base_href = ""

    # ---- 工具 ----
    def _flush(self):
        if self.cur is not None:
            if self.cur.runs or self.cur.is_img:
                self.blocks.append(self.cur)
            self.cur = None

    def _new(self, tag):
        self._flush()
        b = Blk(tag)
        b.size = self.base
        b.color = (28, 30, 36)
        return b

    def _style_for(self, tag, attrs):
        d = dict((k.lower(), (v or "")) for k, v in attrs)
        cls = (d.get("class") or "").lower().split()
        eid = (d.get("id") or "").lower()
        st = {}
        st.update(self.css.match(tag, cls, eid))
        st.update(parse_style(d.get("style", ""), self.base))
        # 老式属性
        if d.get("color"):
            c = parse_color(d["color"])
            if c:
                st["color"] = c
        if d.get("bgcolor"):
            c = parse_color(d["bgcolor"])
            if c:
                st["bg"] = c
        if d.get("align") in ("left", "right", "center"):
            st["align"] = d["align"]
        if tag == "font":
            if d.get("size"):
                try:
                    n = int(d["size"])
                    st["size"] = {1: 12, 2: 14, 3: 18, 4: 22, 5: 26, 6: 32, 7: 40}.get(
                        n, self.base)
                except Exception:
                    pass
        return st, d

    # ---- 解析 ----
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP:
            self.skip_stack.append(tag)
            if tag == "style":
                self._stylebuf = []
            return
        if self.skip_stack:
            return
        st, d = self._style_for(tag, attrs)

        if tag == "title":
            self.in_title = True
            return
        if tag == "base" and d.get("href"):
            self.base_href = d["href"]
            return
        if tag == "img":
            b = self._new("img")
            b.is_img = True
            b.img_src = d.get("src") or d.get("data-src") or d.get("data-original") or ""
            for k in ("width", "height"):
                v = re.sub(r"[^\d]", "", d.get(k, "") or "")
                if v:
                    if k == "width":
                        b.img_w = int(v)
                    else:
                        b.img_h = int(v)
            self.blocks.append(b)
            self.cur = None
            return

        if tag in BLOCK:
            b = self._new(tag)
            b.size = HEAD_SIZE.get(tag, self.base)
            b.bold = tag in ("h1", "h2", "h3", "h4", "h5", "h6", "th", "b", "strong")
            b.mt = {"h1": 16, "h2": 14, "h3": 12, "p": 8, "li": 4, "ul": 8,
                    "ol": 8, "hr": 10, "pre": 10, "blockquote": 10}.get(tag, 6)
            b.mb = b.mt
            if tag in ("h1", "h2", "h3"):
                b.align = "center" if tag == "h1" else "left"
            if tag == "ul" or tag == "ol":
                self.ol_stack.append(0)
                self._flush()
                self.stack.append((tag, cls_of(d), (d.get("id") or "").lower(), {}))
                return
            if tag == "li":
                depth = len(self.ol_stack)
                b.indent = 18 * max(1, depth)
                if self.ol_stack:
                    self.ol_stack[-1] += 1
                    b.bullet = ("%d. " % self.ol_stack[-1]) if tag == "li" and self._ol(
                        depth) else "• "
                else:
                    b.bullet = "• "
            if tag == "blockquote":
                b.indent = 16
                b.color = (90, 96, 108)
            if tag == "hr":
                b.tag = "hr"
                b.runs = []
                self.blocks.append(b)
                self.cur = None
                return
            self.cur = b
            for k in ("size", "bold", "italic", "color", "bg", "align", "lh", "hide"):
                if k in st:
                    if k == "bold":
                        b.bold = bool(st[k])
                    else:
                        setattr(b, k, st[k])
            self.cur_style = dict(st)
            self.stack.append((tag, cls_of(d), (d.get("id") or "").lower(), dict(st)))
            if tag == "pre":
                self.in_pre += 1
                self.cur.pre = True
            return

        # 行内标签
        st2 = dict(self.cur_style)
        st2.update(st)
        if tag in ("b", "strong"):
            st2["bold"] = True
        elif tag in ("i", "em"):
            st2["italic"] = True
        elif tag == "u":
            st2["underline"] = True
        elif tag == "a":
            href = (d.get("href") or "").strip()
            if href and not href.lower().startswith(("javascript:", "#", "mailto:")):
                st2["link"] = urljoin(self.base_url, href)
                if "color" not in st and "color" not in self.cur_style:
                    st2["color"] = (28, 88, 200)
                st2["underline"] = True
            elif href.startswith("#"):
                st2["link"] = None
        elif tag == "br":
            if self.cur is None:
                self.cur = self._new("p")
                self.cur.size = self.base
            self.cur.runs.append(("\n", dict(self.cur_style)))
            return
        self.stack.append((tag, cls_of(d), (d.get("id") or "").lower(), st2))
        self.cur_style = st2

    def _ol(self, depth):
        return False     # 简化：li 一律用 •（有序列表这里不细分）

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in SKIP and tag.lower() not in ("img", "br", "hr"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP:
            if self.skip_stack:
                while self.skip_stack:
                    t = self.skip_stack.pop()
                    if t == "style":
                        self.css.add("".join(self._stylebuf))
                    if t == tag:
                        break
            return
        if self.skip_stack:
            return
        if tag == "title":
            self.in_title = False
            return
        if tag in BLOCK:
            self._flush()
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break
            if tag in ("ul", "ol") and self.ol_stack:
                self.ol_stack.pop()
            if tag == "pre" and self.in_pre:
                self.in_pre -= 1
        else:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break
        self.cur_style = self.stack[-1][3] if self.stack else {}

    def handle_data(self, data):
        if self.skip_stack:
            if self.skip_stack[-1] == "style":
                self._stylebuf.append(data)
            return
        if self.in_title:
            self.title += data.strip() + " "
            return
        if not data:
            return
        if not self.in_pre:
            data = re.sub(r"[ \t\r\n]+", " ", data)
            if not data.strip() and (self.cur is None or not self.cur.runs):
                return
        if self.cur is None:
            self.cur = self._new("p")
            self.cur.size = self.cur_style.get("size", self.base)
            self.cur.runs = []
        self.cur.runs.append((data, dict(self.cur_style)))

    def close(self):
        HTMLParser.close(self)
        self._flush()
        return self.blocks


def cls_of(d):
    return (d.get("class") or "").lower().split()


def parse(htmltext, base_size=18, base_url=""):
    """返回 (title, blocks)"""
    css = CSS(base_size)
    p = _P(css, base_size, base_url)
    try:
        p.feed(htmltext)
        p.close()
    except Exception:
        pass
    return (p.title.strip(), clean_blocks(p.blocks))


# =====================================================================
#  RSS / Atom 专路
#
#  ★ 为什么值得单独做：必应搜索页的 HTML 是 JS 渲染的（只解析出 3 个块），
#    但 `?format=rss` 返回 **5KB 的 RSS**，1 秒内拿全、3ms 解析完、
#    内容干净可读。这是这台设备上最好用的搜索入口。
# =====================================================================
def _strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _xml_text(el, *names):
    for n in names:
        c = el.find(n)
        if c is not None and (c.text or "").strip():
            return (c.text or "").strip()
    return ""


def parse_rss(text, base_url="", base_size=18):
    """返回 (title, blocks)；不是 RSS/Atom 就返回 None"""
    import xml.etree.ElementTree as ET
    s = (text or "").lstrip()
    if not (s.startswith("<?xml") or s.startswith("<rss") or s.startswith("<feed")):
        return None
    try:
        root = ET.fromstring(s)
    except Exception:
        return None

    def lname(t):
        return t.rsplit("}", 1)[-1].lower()

    # 收集 item/entry
    items = [e for e in root.iter() if lname(e.tag) in ("item", "entry")]
    if not items:
        return None
    chan = None
    for e in root:
        if lname(e.tag) in ("channel", "feed"):
            chan = e
            break
    title = ""
    if chan is not None:
        title = _strip_tags(_xml_text(chan, "title"))
    if not title:
        title = "搜索结果"

    blocks = []
    h = Blk("h2")
    h.size = 24
    h.bold = True
    h.align = "left"
    h.mt = 4
    h.mb = 10
    h.runs = [(title, {"size": 24, "bold": True})]
    blocks.append(h)

    for i, it in enumerate(items[:40]):
        t = _strip_tags(_xml_text(it, "title"))
        link = _xml_text(it, "link")
        if not link:
            for e in it:
                if lname(e.tag) == "link" and e.get("href"):
                    link = e.get("href")
                    break
        desc = _strip_tags(_xml_text(it, "description", "summary", "content"))
        if not t and not desc:
            continue
        # 标题（前面带序号）做成链接
        a = Blk("p")
        a.size = 21
        a.bold = True
        a.indent = 2
        a.mt = 12
        a.mb = 2
        a.color = (28, 88, 200)
        a.runs = [("%d. " % (i + 1), {"size": 18, "color": (140, 148, 162)}),
                  (t or link[:60], {"size": 21, "bold": True,
                                    "color": (28, 88, 200), "underline": True,
                                    "link": urljoin(base_url, link) if link else None})]
        a.url = link
        blocks.append(a)
        if desc and desc != t:
            d = Blk("p")
            d.size = 16
            d.indent = 30
            d.mt = 0
            d.mb = 6
            d.color = (78, 84, 96)
            d.lh = 1.28
            d.runs = [(desc[:400], {"size": 16, "color": (78, 84, 96)})]
            blocks.append(d)
        if link:
            u = Blk("p")
            u.size = 13
            u.indent = 30
            u.mt = 0
            u.mb = 4
            u.color = (130, 150, 120)
            u.runs = [(link[:110], {"size": 13, "color": (108, 150, 108),
                                    "link": urljoin(base_url, link), "underline": True})]
            blocks.append(u)
    return title, blocks


def parse_any(text, ctype="", base_url="", base_size=18):
    """自动选 HTML 还是 RSS"""
    low = (ctype or "").lower()
    head = (text or "")[:400].lstrip().lower()
    if ("xml" in low or "rss" in low or head.startswith("<?xml")
            or head.startswith("<rss") or head.startswith("<feed")):
        r = parse_rss(text, base_url, base_size)
        if r is not None:
            return r
    return parse(text, base_size, base_url)


def clean_blocks(blocks):
    out = []
    for b in blocks:
        if b.hide:
            continue
        if b.is_img:
            if b.img_src:
                out.append(b)
            continue
        runs = []
        for t, st in b.runs:
            if t == "\n":
                runs.append((t, st))
                continue
            if t.strip():
                runs.append((t, st))
            elif runs and runs[-1][0] != "\n":
                runs.append((" ", st))
        b.runs = runs
        if b.runs:
            out.append(b)
    return out


# =====================================================================
#  排版：把块流排成"绝对坐标的绘制项"
# =====================================================================
_CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f]")


def _units(s):
    """宽度单位：全角 1.0，半角 0.5"""
    n = len(s)
    if n == 0:
        return 0.0
    a = len(s.encode("ascii", "ignore"))
    return n - 0.5 * a


def tokenize(text):
    """切词：连续 ASCII 非空白算一个词；每个汉字单独一个词；空白当分隔"""
    out = []
    buf = []
    for ch in text:
        if ch == "\n":
            if buf:
                out.append("".join(buf)); buf = []
            out.append("\n")
        elif ch.isspace():
            if buf:
                out.append("".join(buf)); buf = []
            out.append(" ")
        elif ord(ch) > 0x2E7F:
            if buf:
                out.append("".join(buf)); buf = []
            out.append(ch)
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


class Doc(object):
    def __init__(self, title="", url=""):
        self.title = title
        self.url = url
        self.items = []       # ("text",x,y,text,size,bold,italic,color,under,line_id)
        self.links = []       # (x0,y0,x1,y1,url)
        self.height = 0
        self.n_img = 0
        self.n_txt = 0
        self.line_id = 0


def layout(scr, doc, width=1024, pad=14, img_fetch=None,
           max_img_bytes=400 * 1024, max_h=420, max_items=4000):
    """把 doc.blocks 排成绘制项。img_fetch(src)->PIL.Image or None"""
    x0 = pad
    avail = width - pad * 2
    y = pad
    unit_cache = {}
    rcache = {}

    def upx(size):
        v = unit_cache.get(size)
        if v is None:
            v = scr.tw("汉", size, cn=True) or size
            unit_cache[size] = v
        return v

    def rw(s, size, bold):
        """一个词的真实像素宽度。

        ★ 关键优化：**纯 CJK 的词直接按单元宽度算**（这些字体里汉字等宽，
          量它纯属浪费），只有含 ASCII 的词才真去 getsize。
          再配合缓存，一页的测量次数从"每个词"降到"每个不同的英文词"。
        """
        if not s:
            return 0.0
        k = (s, size, bold)
        v = rcache.get(k)
        if v is not None:
            return v
        if all(ord(c) > 0x2E7F for c in s):
            v = len(s) * upx(size)
        else:
            try:
                v = scr.tw(s, size, cn=True)
            except Exception:
                v = _units(s) * upx(size)
            if bold:
                v *= 1.02
        if len(rcache) < 30000:
            rcache[k] = v
        return v

    def twidth(s, size, bold):
        return rw(s, size, bold)

    for b in doc.blocks:
        if len(doc.items) > max_items:
            break
        y += b.mt
        if b.tag == "hr":
            doc.items.append(("rect", x0, y, avail, 1, (196, 202, 214)))
            y += 10
            continue

        if b.is_img:
            # ★ 默认只占位，不在这里抓图 —— 实测某页面 27 张图会让排版卡 23.8 秒。
            #   真图由界面在绘制时按需加载（带后台线程 + 缓存）。
            if img_fetch is None:
                w = int(b.img_w or avail)
                if w > avail:
                    w = avail
                h = int(b.img_h or (w * 0.55))
                if b.img_w and b.img_h:
                    if w > avail:
                        h = int(h * avail / float(b.img_w)); w = avail
                if h > max_h:
                    w = int(w * max_h / float(h)); h = max_h
                if w >= 16 and h >= 16:
                    doc.items.append(("imgph", (width - w) // 2, y, w, h, b.img_src))
                    y += h + 8
                continue
            im = None
            try:
                im = img_fetch(b.img_src)
            except Exception:
                im = None
            if im is not None:
                w = b.img_w or im.width
                h = b.img_h or im.height
                if w > avail:
                    h = int(h * avail / float(w)); w = avail
                if h > max_h:
                    w = int(w * max_h / float(h)); h = max_h
                if w >= 8 and h >= 8:
                    doc.items.append(("img", (width - w) // 2, y, w, h, im))
                    y += h + 6
                    doc.n_img += 1
            continue

        # ---- 文本块：切词 -> 贪心换行 ----
        size0 = b.size
        left = x0 + b.indent
        right = x0 + avail
        maxw = right - left
        toks = []
        if b.bullet:
            toks.append((b.bullet, size0, b.bold, b.italic, b.color, b.url, False))
        for t, st in b.runs:
            sz = st.get("size", size0)
            bd = st.get("bold", b.bold)
            it = st.get("italic", b.italic)
            co = st.get("color", b.color)
            ln = st.get("link")
            un = st.get("underline", False)
            for w in tokenize(t):
                toks.append((w, sz, bd, it, co, ln, un))
        if not toks:
            y += b.mb
            continue

        lines = []
        cur = []
        curw = 0.0
        line_h = 0
        for tk in toks:
            t = tk[0]
            if t == "\n":
                lines.append((cur, line_h)); cur = []; curw = 0.0; line_h = 0
                continue
            if t == " " and not cur:
                continue
            wpx = twidth(t, tk[1], tk[2])
            lh = int(tk[1] * b.lh)
            if cur and curw + wpx > maxw:
                lines.append((cur, line_h))
                cur = [(t, tk, 0.0)]; curw = wpx; line_h = lh
                if t == " ":
                    cur = []; curw = 0.0
            else:
                cur.append((t, tk, curw))
                curw += wpx
                line_h = max(line_h, lh)
        if cur:
            lines.append((cur, line_h))

        for li, (line, lh) in enumerate(lines):
            if not line:
                y += max(4, lh // 2)
                continue
            total = 0.0
            for t, tk, off in line:
                total = off + twidth(t, tk[1], tk[2])
            dx = 0
            if b.align == "center":
                dx = int((maxw - total) / 2)
            elif b.align == "right":
                dx = int(maxw - total)
            lh = lh or int(size0 * b.lh)
            # ★ 给每行一个 line_id：绘制时按行"顺序推进 + 用真实宽度"，
            #   不能靠估算宽度给每个词定位（实测会重叠/挤在一起）。
            doc.line_id += 1
            lid = doc.line_id
            first = True
            for t, tk, off in line:
                tx = left + dx + (0 if first else int(off))
                if first:
                    tx = left + dx
                    first = False
                doc.items.append(("text", tx, y, t, tk[1], tk[2], tk[3], tk[4],
                                  tk[6], lid))
                doc.n_txt += 1
                if tk[5] and t.strip():
                    lr = doc.links
                    if lr and lr[-1][4] == tk[5] and abs(lr[-1][3] - (y + lh)) <= 2 \
                            and lr[-1][0] <= tx <= lr[-1][2] + 40:
                        lr[-1] = (lr[-1][0], lr[-1][1],
                                  tx + int(twidth(t, tk[1], tk[2])), y + lh, tk[5])
                    else:
                        lr.append((tx, y, tx + int(twidth(t, tk[1], tk[2])), y + lh, tk[5]))
            y += lh
        y += b.mb

    doc.height = y + pad
    return doc

