#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preview_all.py —— 本地渲染【整合后的桌面】: 卡片首页 + 图标页 (不需要板子)"""
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


class FakeTouch:
    def poll(self, move=False):
        return None


fbui.Screen = FakeScreen


def out_dir():
    d = os.path.join(os.path.dirname(UI), "界面预览")
    os.makedirs(d, exist_ok=True)
    return d


def build():
    import desktop
    desktop.Screen = FakeScreen
    desktop.Touch = FakeTouch
    import home
    home.Screen = FakeScreen

    d = desktop.Desktop.__new__(desktop.Desktop)
    d.scr = FakeScreen()
    d.touch = FakeTouch()
    APPS = desktop.APPS
    n_slots = 12
    d.pages = []
    names = [a["name"] for a in APPS]
    for i in range(0, max(n_slots, len(names)), n_slots):
        chunk = names[i:i + n_slots]
        d.pages.append(chunk + [None] * (n_slots - len(chunk)))
    while len(d.pages) < 2:
        d.pages.append([None] * n_slots)
    d.page = 0
    d.menu_open = False
    d.last_clock = ""
    d.cpu = 42
    d.last_cpu_t = 0
    d._cpu_prev = None
    d.drag = None
    d.drag_pos = (0, 0)
    d.drag_from = -1
    d.drag_from_page = 0
    d.press_t = 0.0
    d.down_xy = None
    d.grab_off = (0, 0)
    d.pressed = None
    d.anim = None
    d.swipe_x = None
    d.swipe_y = None
    d.swipe_t = 0.0
    d.edge_t = 0.0
    d._bg = None
    d.wall = d.make_wallpaper()
    d._wall_stamp = None
    d.at_home = True
    d.home = None
    d._init_home()
    if d.home is not None:
        # 让首页的卡片有数据可显示
        d.home.info.cpu = 42
        d.home.info.mem_used = 103
        d.home.info.mem_total = 1004
        d.home.info.disk_pct = 8
        d.home.info.temp = 45
        d.home.info.wifi_up = True
        d.home.info.wifi_ssid = "CMCC-Y2Ss"
        d.home.info.wifi_ip = "192.168.10.18"
        d.home.info.wifi_qual = 97
        d.home.info.wifi_dbm = -32
        d.home.info.weather = {"temp": 25, "text": "晴", "city": "北京", "hi": 28, "lo": 17,
                               "kind": "sun", "hum": 55, "age": "12 分钟前"}
        d.home.info.music_title = "夜航星"
        d.home.info.music_artist = "不才"
        d.home.info.music_pos = 87
        d.home.info.music_len = 254
        d.home.info.music_playing = True
    return d


def render(name, fn):
    d = build()
    fn(d)
    p = os.path.join(out_dir(), name)
    d.scr.img.save(p)
    print("  -> %s" % p)


def main():
    print("[整合预览]")
    render("整合_卡片首页.png", lambda d: (setattr(d, "at_home", True), d.draw()))
    render("整合_图标页.png", lambda d: (setattr(d, "at_home", False),
                                        setattr(d, "page", 0), d.draw()))
    render("整合_图标页2.png", lambda d: (setattr(d, "at_home", False),
                                         setattr(d, "page", 1), d.draw()))


main()
