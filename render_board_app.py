#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_board_app.py —— ★ 在 PC 上离屏渲染板载 App 的界面

════════════════════════════════════════════════════════════════════
为什么要这个
════════════════════════════════════════════════════════════════════
板载 App 是直接画到 framebuffer 的，改一次要传到板子、重启桌面才能看效果，
而且要看设置页还得用手指点。

⇒ 这里在 PC 上造一个【和 fbui.Screen 接口一样的假 Screen】，
  再给 apps_agent 一个假的 fbui 模块，然后直接调它的 draw()，
  渲染成 PNG。这样改界面 → 出图 → 看效果，几秒钟一轮。

★ 字体不一样（板子上是位图字体，这里是系统字体），
  但布局、颜色、位置和板子上是一致的，够用来检查排版。

用法:
    python render_board_app.py                 # 主界面
    python render_board_app.py --settings      # 设置页
    python render_board_app.py --muted         # 静音状态
    python render_board_app.py --all           # 全部出一遍
"""
import argparse
import os
import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
from PIL import Image, ImageDraw, ImageFont   # noqa: E402

W, H = 1024, 600


# ══════════════════════════════════════════════════════════════════
#  假 fbui
# ══════════════════════════════════════════════════════════════════
def _font(size, cn=False):
    """找一个能显示中文的字体"""
    for name in ("msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc",
                 "Deng.ttf", "arial.ttf"):
        for d in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
    return ImageFont.load_default()


class FakeScreen(object):
    """接口和 fbui.Screen 一样，但画到内存里的 PIL 图"""

    def __init__(self):
        self.w, self.h = W, H
        self.img = Image.new("RGB", (W, H), (12, 16, 32))
        self.d = ImageDraw.Draw(self.img)
        self._fc = {}

    def _f(self, size, cn=False):
        k = (size, cn)
        if k not in self._fc:
            self._fc[k] = _font(size, cn)
        return self._fc[k]

    def clear(self, c=(12, 16, 32)):
        self.d.rectangle([0, 0, self.w, self.h], fill=c)

    def fill(self, x, y, w, h, color):
        self.d.rectangle([x, y, x + w, y + h], fill=color)

    def rect(self, xy, fill=None, outline=None, width=1):
        self.d.rectangle(xy, fill=fill, outline=outline, width=width)

    def rrect(self, xy, r, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = xy
        self.d.rounded_rectangle([x0, y0, x1, y1], radius=max(0, r),
                                 fill=fill, outline=outline, width=width)

    def line(self, xy, fill=(255, 255, 255), width=1):
        self.d.line(xy, fill=fill, width=width)

    def tw(self, s, size=20, bold=False, cn=False, mono=False):
        """量文字宽度 —— 和板子上的 tw 语义一致"""
        f = self._f(size, cn)
        try:
            return int(self.d.textlength(s, font=f))
        except Exception:
            return len(s) * size // 2

    def text(self, xy, s, size=20, fill=(255, 255, 255), bold=False, cn=False,
             anchor=None, mono=False):
        f = self._f(size, cn)
        amap = {"lm": "lm", "mm": "mm", "rm": "rm", "la": "la", "ma": "ma",
                "ra": "ra", None: "la"}
        a = amap.get(anchor, "la")
        try:
            self.d.text(xy, s, font=f, fill=fill, anchor=a)
        except Exception:
            self.d.text(xy, s, font=f, fill=fill, anchor="la")

    def flush(self, box=None):
        pass


def hit(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def btn(scr, rect, label, fill=(56, 88, 148), tc=(255, 255, 255), size=22,
        cn=False, radius=10, bold=False, outline=None, mono=False):
    scr.rrect(list(rect), radius, fill=fill, outline=outline,
              width=2 if outline else 1)
    scr.text(((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2), label,
             size, tc, cn=cn, anchor="mm", bold=bold, mono=mono)


def header(scr, title, accent=(70, 110, 180), bg=(30, 40, 68), cn=True):
    scr.rect([0, 0, scr.w, 60], fill=bg)
    scr.rect([0, 58, scr.w, 62], fill=accent)
    btn(scr, [10, 8, 130, 52], "< 返回", fill=(60, 70, 100), size=22, cn=True)
    scr.text((150, 30), title, 26, (238, 244, 255), cn=cn, anchor="lm")


def back_hit(x, y):
    return hit([10, 8, 130, 52], x, y)


class MiniKeyboard(object):
    ROWS = [list("1234567890"), list("qwertyuiop"), list("asdfghjkl."),
            list("zxcvbnm_-/")]

    def __init__(self, y0=372, key_w=88, key_h=48, gap=6):
        self.y0, self.kw, self.kh, self.gap = y0, key_w, key_h, gap
        self.keys = []
        for r, row in enumerate(self.ROWS):
            total = len(row) * key_w + (len(row) - 1) * gap
            x = (W - total) // 2
            y = self.y0 + r * (key_h + gap)
            for ch in row:
                self.keys.append((ch, [x, y, x + key_w, y + key_h]))
                x += key_w + gap
        y = self.y0 + len(self.ROWS) * (key_h + gap)
        self.keys.append(("<BS>", [280, y, 500, y + key_h]))
        self.keys.append(("<ENTER>", [510, y, 745, y + key_h]))

    def draw(self, scr):
        for ch, r in self.keys:
            label = {"<BS>": "退格", "<ENTER>": "回车"}.get(ch, ch)
            btn(scr, r, label, fill=(40, 48, 68), size=18,
                cn=(ch in ("<BS>", "<ENTER>")))

    def press(self, x, y):
        for ch, r in self.keys:
            if hit(r, x, y):
                return ch
        return None


# ★ 把假 fbui 塞进 sys.modules，这样 apps_agent 的 import 就拿到假的
fake = types.ModuleType("fbui")
fake.Screen = FakeScreen
fake.hit = hit
fake.btn = btn
fake.header = header
fake.back_hit = back_hit
fake.MiniKeyboard = MiniKeyboard
sys.modules["fbui"] = fake

import apps_agent as AA      # noqa: E402


def render(mode="main", out=None):
    scr = FakeScreen()
    app = AA.AgentApp.__new__(AA.AgentApp)     # ★ 不跑 __init__（会去连网络）
    # 手动把界面需要的东西填上
    app.msgs = [
        ("bot", "我是系统管家小白 —— 这块板子的系统管家。"),
        ("sys", "打字后按回车问我；也可以点「按住说话」用说的。"),
        ("user", "现在多少度"),
        ("bot", "现在 65.7 度，正常。守护会在超过 85 度时开始降载。"),
        ("user", "板载示波器的采样率是多少"),
        ("bot", "scope_cap_axi 在 0x43CC0000：4096 点 × 8 bit 双 bank，"
                "采样率 = 100 MHz / DIV，DIV=5 时 20 MSPS。"),
    ]
    app.lines = []
    app.cur = ""
    app.py = ""
    app.cands = []
    app.pinyin = True
    app.quick = 0
    app.pending = []
    app.bar_rendered = []
    app.busy = ""
    app.last_reply = ""
    app.kb = MiniKeyboard(y0=AA.KB_Y, key_w=76, key_h=AA.KB_KH, gap=AA.KB_GAP)
    app.muted = (mode == "muted")
    app.settings_open = (mode == "settings")
    app.settings_page = 0
    app.settings_hit = {}
    app.models = ["deepseek-flash", "deepseek-v4-pro"]
    app.cur_model = "deepseek-v4-pro"
    app.has_key = True
    app.api_base = "https://api.deepseek.com"
    app._settings_dirty = False
    app._rec_until = 0.0
    app.await_key = False
    app._pend_t = 0.0
    app.mode = "auto"
    app.kb_open = bool(mode in ("kb",))
    app.sessions = [("现在多少度", ""), ("波形识别怎么用", ""),
                    ("温度多少", ""), ("改个 FPGA", "")]
    app.cur_session = 1

    btns = app.buttons(scr)
    app.draw(scr, btns)
    out = out or os.path.join(HERE, "board_ui_%s.png" % mode)
    scr.img.save(out)
    print("  ✓ %-9s -> %s" % (mode, out))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", action="store_true")
    ap.add_argument("--muted", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    print("=" * 66)
    print(" 板载 App 离屏渲染")
    print("=" * 66)
    if a.all or not (a.settings or a.muted):
        render("main")
    if a.all or a.muted:
        render("muted")
    if a.all or a.settings:
        render("settings")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
