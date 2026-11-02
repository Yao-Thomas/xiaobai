#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preview_home.py —— 在电脑上渲染卡片首页, 出 PNG (完全不需要板子)

用法: python preview_home.py [all|empty|full]
  empty : 没网、没音乐的状态 (最朴素的样子)
  full  : 有天气、正在播放音乐、有网的状态
"""
import os
import sys
import datetime

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


class FakeInfo:
    """假的系统数据 —— 让预览图好看且可复现"""

    def __init__(self, full=False):
        self.dt = datetime.datetime(2026, 9, 26, 14, 24, 36)
        self.t = self.dt.timetuple()
        self.cpu = 42
        self.mem_used = 103
        self.mem_total = 1004
        self.disk_pct = 8
        self.temp = 45
        self.wifi_up = full
        self.wifi_ssid = "CMCC-Y2Ss" if full else ""
        self.wifi_ip = "192.168.10.18" if full else ""
        self.wifi_qual = 78 if full else 0
        self.wifi_dbm = -32 if full else 0
        self.music_title = "夜航星" if full else ""
        self.music_artist = "不才" if full else ""
        self.music_pos = 87 if full else 0
        self.music_len = 254 if full else 0
        self.music_playing = full
        self.weather = ({"temp": 25, "text": "晴", "city": "北京", "hi": 28, "lo": 17,
                         "kind": "sun", "hum": 55, "age": "12 分钟前"}
                        if full else None)

    def tick(self, force=False):
        return self


def out_dir():
    d = os.path.join(os.path.dirname(UI), "界面预览")
    os.makedirs(d, exist_ok=True)
    return d


def render(name, full=False):
    import home
    home.Screen = FakeScreen
    scr = FakeScreen()
    info = FakeInfo(full=full)

    apps, icons = [], {}
    try:
        import desktop
        apps = [dict(a) for a in desktop.APPS]
        for a in desktop.APPS:
            icons[a["name"]] = a["icon"]
    except Exception as ex:
        print("   (拿不到 desktop.APPS: %s)" % ex)
        apps = [{"name": n, "tint": t} for n, t in
                (("扫雷", (225, 80, 70)), ("计算器", (240, 160, 50)),
                 ("画板", (60, 195, 150)), ("文件", (90, 150, 240)))]

    h = home.Home(scr, info=info, apps=apps, icons=icons)
    h.draw(full=True)
    p = os.path.join(out_dir(), "首页_%s.png" % name)
    scr.img.save(p)
    print("  -> %s" % p)
    return p


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("[首页预览]")
    if which in ("all", "empty"):
        render("无网无音乐", full=False)
    if which in ("all", "full"):
        render("联网有音乐", full=True)


main()
