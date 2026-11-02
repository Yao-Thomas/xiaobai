#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps_novel.py —— 小说阅读器（.txt）

功能：
  · 书架（扫描几个目录里的 .txt，显示大小 / 进度 / 书签数）
  · 自动分页（按字号重排；只存"每页起始偏移"，不存正文）
  · 字号 6 档、主题 3 种（纸白 / 米黄 / 夜间）
  · 书签 + 书签跳转
  · 自动记忆阅读进度（退出/切书都存，`~/.novel_pos.json`）
  · 点屏幕左 1/3 上一页、右 1/3 下一页

文件编码：utf-8-sig → utf-8 → gb18030 → big5 → utf-16 依次尝试
  （中文小说绝大多数是 GBK/GB18030，直接按 utf-8 读会全是乱码）

★ 上板实测后做的三处性能修复（都有数据支撑，见 perf 记录）：
  1) 分页 7.5s -> 0.6s：原来逐字符 Python 循环 + 每行切片整个剩余段落（O(n²)）。
     改成按 '\\n' 切段 + 整段宽度只算一次 + 按密度估算断点 + C 层 re.sub 算宽度。
  2) 翻页 117ms -> 约 45ms：cProfile 显示 `Font.getsize` 白花 30ms/帧
     （`anchor` 每次重新量宽度），6 个按钮的圆角+文字又是 12 次 render。
     改成：文字宽度加缓存 + 顶栏/底栏做成缓存位图，一帧只 paste 两次。
  3) 空闲 30fps 满负载重绘 -> 只在状态变化时重绘（dirty 标记）。
     原来 while 循环每 30ms 无条件整屏重画，空闲时也在烧 CPU。
"""
import os
import json
import time

from PIL import Image, ImageDraw

from fbui import header, back_hit, btn, hit, font

BOOK_DIRS = ["/home/zynq/Books", "/home/zynq/小说", "/home/zynq/Documents",
             "/home/zynq/Downloads"]
POS_FILE = "/home/zynq/.novel_pos.json"
MARK_FILE = "/home/zynq/.novel_marks.json"

FONTS = [20, 24, 28, 32, 38, 46]
THEMES = [
    ("纸白", (246, 243, 235), (52, 46, 40), (222, 216, 204)),
    ("米黄", (238, 226, 198), (74, 58, 38), (206, 190, 158)),
    ("夜间", (20, 22, 28), (183, 183, 183), (47, 47, 47)),
]

TXT_X0, TXT_Y0, TXT_X1, TXT_Y1 = 44, 76, 980, 524
BAR_Y0 = 534
BOT_Y0 = 528                      # 底部缓存条从这里开始


# ======================= 存取 =======================
def _load_json(p, d):
    try:
        o = json.load(open(p))
        return o if isinstance(o, dict) else d
    except Exception:
        return d


def _save_json(p, o):
    try:
        json.dump(o, open(p, "w"), ensure_ascii=False)
    except Exception:
        pass


def _decode(raw):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16"):
        try:
            t = raw.decode(enc)
            if enc in ("gb18030", "big5"):
                if sum(1 for c in t[:4000] if c == "\ufffd") > 20:
                    continue
            return t, enc
        except Exception:
            continue
    return raw.decode("utf-8", "replace"), "utf-8(replace)"


def _norm(t):
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    for c in ("\ufeff", "\u200b", "\u200e", "\u200f"):
        t = t.replace(c, "")
    return t


def scan_books():
    out = []
    for d in BOOK_DIRS:
        if not os.path.isdir(d):
            continue
        base_depth = d.count(os.sep)
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            if root.count(os.sep) - base_depth > 2:
                dirs[:] = []
                continue
            for f in files:
                if not f.lower().endswith((".txt", ".text")):
                    continue
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                    if st.st_size < 200:
                        continue
                    out.append((p, st.st_size, st.st_mtime))
                except Exception:
                    pass
    out.sort(key=lambda x: -x[2])
    return out


# ======================= 分页 =======================
def _w(s):
    """一段的排版宽度（全角=1，半角=0.5）。

    ★ 用 str.encode('ascii','ignore') 这种 C 层操作数 ASCII 字符个数，
      不在 Python 里逐字符循环（第一版逐字符循环在 2MB 上要 7.5 秒）。
      宽度 = 非ASCII*1 + ASCII*0.5 = n - 0.5*ascii
    """
    n = len(s)
    if n == 0:
        return 0.0
    a = len(s.encode("ascii", "ignore"))
    return n - 0.5 * a


def paginate(text, cpl, lpp):
    """返回每页起始偏移列表（只存 int，2MB 的书也只是一个整数表）

    ★ 性能踩过的坑（上板实测）：
      1) 逐字符 Python 循环 -> 220 万次迭代，2.2MB 要 7.5 秒。
      2) 每行 `_w(para[i:])` 切片整个剩余段落 -> O(n²)，仍要 5 秒。
      3) 断点用"估算 + 线性回退"，中文里夹英文时估算偏差大，
         一次回退十几步，又变成 5 秒。改成**二分**，最多 ~7 次 _w/行。

      最终三条路：
        · 纯全角段落（中文小说 99%）-> 每行正好 cpl 个字，0 次 _w
        · 纯半角段落（英文小说）    -> 每行正好 2*cpl 个字符，0 次 _w
        · 中英混排                -> 二分找断点，≤7 次 _w/行
    """
    n = len(text)
    starts = [0]
    pos = 0
    lines = 0
    for para in text.split("\n"):
        plen = len(para)
        if lines >= lpp:
            starts.append(pos)
            lines = 0
        if plen == 0:
            pos += 1
            lines += 1
            continue
        rem_w = _w(para)
        dens = rem_w / plen
        # ★ 安全的关键：一行放 cpl 个字符，宽度**永远不会超过 cpl 个单位**
        #   （因为每个字符最宽就是 1 个单位）。所以阈值可以放宽到 0.90，
        #   代价只是"行稍微短一点"，绝不会溢出。这样"中文里夹少量英文/
        #   数字"这种真实小说也能走 0 次 _w 的快路径。
        dense_cjk = dens >= 0.90                  # 全角为主
        dense_asc = dens <= 0.52                  # 半角为主
        if dense_cjk or dense_asc:
            step = cpl if dense_cjk else 2 * cpl
            i = 0
            while i < plen:
                k = step if i + step < plen else plen - i
                i += k
                lines += 1
                if lines >= lpp and i < plen:
                    starts.append(pos + i)
                    lines = 0
            pos += plen + 1
            continue
        # 中英混排：二分找断点（宽度随 k 单调，二分一定对）
        i = 0
        while i < plen:
            rem = plen - i
            if rem_w <= cpl:
                i = plen
            else:
                hi = rem if rem < 2 * cpl else 2 * cpl
                lo = 1
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if _w(para[i:i + mid]) <= cpl:
                        lo = mid
                    else:
                        hi = mid - 1
                k = lo
                i += k
                rem_w -= _w(para[i - k:i])
                if rem_w < 0:
                    rem_w = 0.0
            lines += 1
            if lines >= lpp and i < plen:
                starts.append(pos + i)
                lines = 0
        pos += plen + 1
    while len(starts) > 1 and starts[-1] >= n:
        starts.pop()
    return starts


def metrics(scr, size):
    w1 = scr.tw("汉", size, cn=True) or size
    # ★ 留 7% 余量：宽度模型把 "→"、"①"、括号这类字符按 0.5/1 单位估，
    #   但字体实际渲染出来会宽一些，不给余量就会出现"最后两个字被切在屏幕外"。
    cpl = max(8, int((TXT_X1 - TXT_X0) * 0.93 / max(1.0, w1)))
    asc, desc = font(size, cn=True).getmetrics()
    lh = asc + desc + max(3, size // 6)
    lpp = max(3, int((TXT_Y1 - TXT_Y0) / lh))
    return cpl, lpp, lh


# ======================= 阅读器 =======================
class Reader(object):
    def __init__(self, path):
        self.path = path
        raw = open(path, "rb").read()
        self.text, self.enc = _decode(raw)
        self.text = _norm(self.text)
        self.pos = _load_json(POS_FILE, {})
        self.marks = _load_json(MARK_FILE, {})
        st = self.pos.get(path, {})
        self.size = int(st.get("size", FONTS[1]))
        self.theme = int(st.get("theme", 1))
        self._page0 = int(st.get("page", 0))
        self.cpl = self.lpp = self.lh = 0
        self.starts = None
        self.page = 0
        self.mark = list(self.marks.get(path, []))

    @property
    def title(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    def layout(self, scr):
        """分页。★ 改字号时必须保持阅读位置（记住页首字符偏移，重排后找回来）"""
        cpl, lpp, lh = metrics(scr, self.size)
        if (cpl, lpp) == (self.cpl, self.lpp) and self.starts:
            return
        import bisect
        first = self.starts is None
        off = 0 if first else self.starts[self.page]
        self.cpl, self.lpp, self.lh = cpl, lpp, lh
        self.starts = paginate(self.text, cpl, lpp)
        if first:
            self.page = max(0, min(self._page0, len(self.starts) - 1))
        else:
            self.page = max(0, min(bisect.bisect_right(self.starts, off) - 1,
                                   len(self.starts) - 1))

    def npages(self):
        return max(1, len(self.starts or [1]))

    def page_text(self):
        s = self.starts[self.page]
        e = self.starts[self.page + 1] if self.page + 1 < len(self.starts) else len(self.text)
        return self.text[s:e]

    def save(self):
        self.pos[self.path] = {"page": self.page, "size": self.size,
                               "theme": self.theme, "ts": time.time()}
        _save_json(POS_FILE, self.pos)
        self.marks[self.path] = sorted(set(self.mark))
        _save_json(MARK_FILE, self.marks)

    def colors(self):
        t = THEMES[self.theme]
        return t[1], t[2], t[3]


def buttons():
    labels = ["上一页", "下一页", "A-", "A+", "书签", "主题"]
    bw, gp = 138, 14
    x = (1024 - (len(labels) * bw + (len(labels) - 1) * gp)) // 2
    return [(t, [x + i * (bw + gp), BAR_Y0, x + i * (bw + gp) + bw, BAR_Y0 + 56])
            for i, t in enumerate(labels)]


def _rr(d, box, radius, fill):
    x0, y0, x1, y1 = box
    r = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    if r <= 0:
        d.rectangle(box, fill=fill)
        return
    d.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    d.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    for cx, cy in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
        d.ellipse([cx, cy, cx + 2 * r - 1, cy + 2 * r - 1], fill=fill)


_CHROME = {}


def chrome(scr, theme, marked):
    """顶栏/底栏的缓存位图。

    ★ 为什么：cProfile 显示一帧 16.7 次文字 render，其中 6 个按钮的
      圆角+文字就占 12 次（render 3.7ms/次）。缓存后一帧只要 paste 两次。
    """
    k = (theme, marked)
    c = _CHROME.get(k)
    if c is not None:
        return c
    bg, fg, dim = THEMES[theme][1], THEMES[theme][2], THEMES[theme][3]
    top = Image.new("RGB", (1024, 62), bg)
    dt = ImageDraw.Draw(top)
    dt.rectangle([0, 58, 1024, 62], fill=dim)
    _rr(dt, [10, 8, 120, 52], 10, (74, 74, 74))
    f20 = font(20, cn=True)
    tw = scr.tw("< 返回", 20, cn=True)
    asc, desc = f20.getmetrics()
    dt.text((65 - tw / 2, 30 - (asc + desc) / 2), "< 返回", font=f20, fill=(255, 255, 255))

    bot = Image.new("RGB", (1024, 600 - BOT_Y0), bg)
    db = ImageDraw.Draw(bot)
    for t, rect in buttons():
        col = (196, 148, 40) if (t == "书签" and marked) else (70, 70, 70)
        r = [rect[0], rect[1] - BOT_Y0, rect[2], rect[3] - BOT_Y0]
        _rr(db, r, 12, col)
        sz = 20 if len(t) > 2 else 24
        f = font(sz, cn=True)
        tw = scr.tw(t, sz, cn=True)
        a2, d2 = f.getmetrics()
        db.text(((r[0] + r[2]) / 2 - tw / 2,
                 r[1] + (r[3] - r[1] - a2 - d2) / 2), t, font=f, fill=(255, 255, 255))
    c = (top, bot)
    _CHROME[k] = c
    return c


_PGC = {}


def _page_img(r):
    """把一页正文渲染成小位图并缓存。

    ★ 上板实测：`Font.render` 渲染 33 个汉字要 5.9ms，一页 10 行就是 59ms。
      缓存之后 —— 往回翻页、切主题再切回来、点书签触发的整屏重绘 ——
      全都变成一次 paste（约 1ms）。
    """
    key = (r.path, r.theme, r.size, r.page)
    v = _PGC.get(key)
    if v is not None:
        return v
    bg, fg, dim = r.colors()
    h = TXT_Y1 - TXT_Y0 + 10
    im = Image.new("RGB", (TXT_X1 - TXT_X0, h), bg)
    d = ImageDraw.Draw(im)
    f = font(r.size, cn=True)
    y = 0
    for line in r.page_text().split("\n"):
        if line.strip():
            d.text((0, y), line, font=f, fill=fg)
        y += r.lh
        if y > h:
            break
    if len(_PGC) > 16:
        _PGC.clear()
    _PGC[key] = im
    return im


def draw_reader(scr, r):
    bg, fg, dim = r.colors()
    marked = r.page in r.mark
    top, bot = chrome(scr, r.theme, marked)
    scr.clear(bg)
    scr.img.paste(top, (0, 0))
    scr.img.paste(bot, (0, BOT_Y0))
    scr.img.paste(_page_img(r), (TXT_X0, TXT_Y0))
    # 动态文字
    scr.text((138, 30), r.title, 22, fg, cn=True, anchor="lm")
    n = r.npages()
    pct = int(100.0 * r.page / max(1, n - 1)) if n > 1 else 100
    scr.text((scr.w - 16, 30), "%d/%d  %d%%" % (r.page + 1, n, pct),
             18, fg, cn=True, anchor="rm")
    if r.mark:
        scr.text((scr.w - 210, 30), "★ %d" % len(r.mark), 18,
                 (232, 176, 60) if marked else dim, cn=True, anchor="rm")


def reader(scr, touch, path):
    r = Reader(path)
    # 大文件排版可能要 1 秒以上（中英混排最慢），给个提示，别让用户以为死机了
    try:
        big = os.path.getsize(path) > 400 * 1024
    except Exception:
        big = False
    if big:
        scr.clear((26, 26, 26))
        scr.text((512, 274), "正在排版…", 30, (233, 233, 233), cn=True, anchor="mm")
        scr.text((512, 320), os.path.basename(path)[:44], 18, (150, 168, 200),
                 cn=True, anchor="mm")
        scr.flush()
    dirty = True
    while True:
        if dirty:
            r.layout(scr)
            draw_reader(scr, r)
            scr.flush()
            dirty = False
        ev = touch.poll()
        if not ev:
            time.sleep(0.03)
            continue
        _, x, y = ev
        if back_hit(x, y):
            r.save()
            return
        if y < 62:
            if r.mark and x > 1024 - 240:          # 点 ★ 跳下一个书签
                nxt = [m for m in sorted(r.mark) if m > r.page]
                r.page = nxt[0] if nxt else sorted(r.mark)[0]
                dirty = True
            continue
        if y >= BAR_Y0:
            for t, rect in buttons():
                if not hit(rect, x, y):
                    continue
                if t == "上一页":
                    r.page = max(0, r.page - 1)
                elif t == "下一页":
                    r.page = min(r.npages() - 1, r.page + 1)
                elif t == "A-":
                    i = FONTS.index(r.size) if r.size in FONTS else 1
                    r.size = FONTS[max(0, i - 1)]
                elif t == "A+":
                    i = FONTS.index(r.size) if r.size in FONTS else 1
                    r.size = FONTS[min(len(FONTS) - 1, i + 1)]
                elif t == "书签":
                    if r.page in r.mark:
                        r.mark.remove(r.page)
                    else:
                        r.mark.append(r.page)
                    r.save()
                    print("小说: 书签 %s 第%d页 (共%d个)"
                          % ("加" if r.page in r.mark else "删", r.page + 1, len(r.mark)))
                elif t == "主题":
                    r.theme = (r.theme + 1) % len(THEMES)
                    r.save()
                dirty = True
                break
            continue
        # 正文区：左 1/3 上一页，右 1/3 下一页
        if x < 1024 // 3:
            r.page = max(0, r.page - 1)
            dirty = True
        elif x > 1024 * 2 // 3:
            r.page = min(r.npages() - 1, r.page + 1)
            dirty = True


# ======================= 书架 =======================
ROWH = 78
PER = 5


def draw_shelf(scr, books, pos, marks, top, pressed=None):
    scr.clear((26, 26, 26))
    header(scr, "书架")
    if not books:
        scr.text((512, 240), "还没有书", 30, (237, 237, 237), cn=True, anchor="mm")
        scr.text((512, 300), "把 .txt 小说放进下面任意一个目录，再点「刷新」",
                 20, (150, 168, 200), cn=True, anchor="mm")
        for i, d in enumerate(BOOK_DIRS[:4]):
            scr.text((512, 344 + i * 28), d, 17, (110, 130, 170), mono=True, anchor="mm")
        btn(scr, [412, 500, 612, 556], "刷新", fill=(56, 96, 160), size=24, cn=True)
        return []
    rects = []
    for i in range(min(PER, len(books) - top)):
        p, sz, mt = books[top + i]
        y = 74 + i * ROWH
        rect = [16, y, scr.w - 118, y + ROWH - 10]   # 右边留出滚动/刷新按钮的位置
        rects.append((rect, p))
        pr = pos.get(p, {})
        pg = pr.get("page", 0)
        mk = len(marks.get(p, []))
        sel = (pressed == p)
        scr.rrect(rect, 12, fill=(44, 62, 104) if sel else (40, 40, 40),
                  outline=(96, 126, 180) if sel else (52, 64, 92), width=2)
        name = os.path.splitext(os.path.basename(p))[0]
        scr.text((rect[0] + 18, rect[1] + 14), name[:26], 22, (243, 243, 243), cn=True)
        sub = "%.0f KB" % (sz / 1024.0)
        if pg:
            sub += "   读到第 %d 页" % (pg + 1)
        if mk:
            sub += "   ★%d" % mk
        scr.text((rect[0] + 18, rect[1] + 44), sub, 15, (146, 166, 200), cn=True)
        bx0, bx1 = rect[2] - 150, rect[2] - 20
        by = rect[1] + 34
        scr.rrect([bx0, by, bx1, by + 8], 4, fill=(36, 36, 36))
        if pg:
            fw = int((bx1 - bx0) * min(1.0, (pg + 1) / 400.0))
            scr.rrect([bx0, by, bx0 + max(4, fw), by + 8], 4, fill=(86, 166, 255))
    return rects


def shelf_btns():
    x1 = 1024
    return {"up": [x1 - 92, 92, x1 - 20, 156],
            "dn": [x1 - 92, 168, x1 - 20, 232],
            "rf": [x1 - 92, 244, x1 - 20, 308]}


def shelf(scr, touch):
    books = scan_books()
    pos = _load_json(POS_FILE, {})
    marks = _load_json(MARK_FILE, {})
    top = 0
    dirty = True
    s = shelf_btns()
    while True:
        if dirty:
            rects = draw_shelf(scr, books, pos, marks, top)
            for k, r in s.items():
                btn(scr, r, {"up": "▲", "dn": "▼", "rf": "刷新"}[k],
                    fill=(52, 62, 92), size=22, cn=True, radius=10)
            scr.text((16, scr.h - 26),
                     "共 %d 本 · 目录 %s" % (len(books), BOOK_DIRS[0]),
                     14, (120, 138, 172), cn=True)
            scr.flush()
            dirty = False
        ev = touch.poll()
        if not ev:
            time.sleep(0.03)
            continue
        _, x, y = ev
        if back_hit(x, y):
            return
        if hit(s["up"], x, y):
            top = max(0, top - 1)
            dirty = True
            continue
        if hit(s["dn"], x, y):
            top = min(max(0, len(books) - PER), top + 1)
            dirty = True
            continue
        if hit(s["rf"], x, y):
            books = scan_books()
            top = 0
            dirty = True
            continue
        for rect, p in rects:
            if hit(rect, x, y):
                print("小说: 打开 %s" % p)
                reader(scr, touch, p)
                pos = _load_json(POS_FILE, {})
                marks = _load_json(MARK_FILE, {})
                dirty = True
                break


def run(scr, touch):
    shelf(scr, touch)
