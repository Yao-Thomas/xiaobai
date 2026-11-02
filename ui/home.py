#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
home.py —— 卡片式起始页（首页）

设计参考：
  · Apple iPadOS 小组件栅格：小 2×2 / 中 4×2 / 大 4×4 / iPad 特大 8×4
  · 华为 HarmonyOS 服务卡片：1×2 / 2×2 / 2×4 / 4×4
  · 共同原则：卡片是"一眼可读"，不是小号应用 —— 一个大数字/图标 + 一行说明；
    不堆信息、不塞按钮、点整张卡进入应用。

本屏 1024×600，取 8 列 × 4 行栅格：
    单元格 111×115，间距 12，左右边距 26，顶部状态栏 30，底部 Dock 72

布局（6 张卡铺满 8×4）：
    ┌──────────────────────┬──────────┬──────────┐
    │  时钟 4×2            │ 天气 2×2 │ 系统 2×2 │
    ├──────────────────────┼──────────┼──────────┤
    │  音乐 4×2            │ 网络 2×2 │ 最近 2×2 │
    └──────────────────────┴──────────┴──────────┘

性能：
  卡片底图（圆角+渐变+玻璃+阴影）**生成一次缓存**；每帧只把静态层 paste 回来，
  再重画"值变了"的那几个小方框，然后 flush(box) 只推这几个方框。
"""
import os
import re
import sys
import time
import math
import threading
import subprocess
import datetime

from PIL import Image, ImageDraw

import fbui

# ---------------- 栅格 ----------------
W, H = 1024, 600
COLS, ROWS = 8, 4
CELL_W, CELL_H = 111, 115
GAP = 12
MARGIN = 26
STATUS_H = 30
DOCK_H = 72
Y0 = STATUS_H

# 卡片: (key, 列, 行, 跨列, 跨行)
CARDS = [
    ("clock",   0, 0, 4, 2),
    ("weather", 4, 0, 2, 2),
    ("system",  6, 0, 2, 2),
    ("music",   0, 2, 4, 2),
    ("network", 4, 2, 2, 2),
    ("recent",  6, 2, 2, 2),
]

# 配色（深色玻璃主题）
C_BG_TOP = (22, 30, 52)
C_BG_BOT = (8, 11, 22)
C_CARD_TOP = (40, 50, 78)
C_CARD_BOT = (18, 24, 40)
C_TEXT = (240, 245, 255)
C_TEXT_DIM = (150, 166, 198)
C_TEXT_FAINT = (104, 120, 150)
C_ACCENT = (76, 141, 246)      # #4C8DF6
C_OK = (52, 199, 89)           # #34C759
C_WARN = (255, 159, 10)        # #FF9F0A
C_BAR_BG = (44, 54, 78)

CARD_R = 18
DOCK_R = 26
DOCK_ITEMS = [
    ("桌面", "home"), ("应用", "apps"), ("小说", "novel"),
    ("浏览器", "browser"), ("音乐", "music"), ("设置", "settings"),
]


def card_rect(col, row, cs, rs):
    x = MARGIN + col * (CELL_W + GAP)
    y = Y0 + row * (CELL_H + GAP)
    w = cs * CELL_W + (cs - 1) * GAP
    h = rs * CELL_H + (rs - 1) * GAP
    return (x, y, x + w, y + h)


# =====================================================================
#  动态数据（全部有离线兜底：读不到就保留上次的值，绝不让首页崩）
# =====================================================================
class Info:
    def __init__(self):
        self.cpu = 0
        self.mem_used = 0
        self.mem_total = 0
        self.disk_pct = 0
        self.temp = None
        self.wifi_ssid = ""
        self.wifi_ip = ""
        self.wifi_qual = 0
        self.wifi_dbm = 0
        self.wifi_up = False
        # SSID 由后台线程取（★ 绝不在 UI 线程里等子进程，见 _kick_ssid）
        self._ssid_busy = False
        self._ssid_t = 0.0
        self.music_title = ""
        self.music_artist = ""
        self.music_pos = 0
        self.music_len = 0
        self.music_playing = False
        self.weather = None         # dict: temp/text/city
        self._prev_cpu = None
        self._last_full = 0.0
        self._last_fast = 0.0
        self.tick(True)

    # ---- 工具 ----
    @staticmethod
    def _read(p, d=None):
        try:
            return open(p).read().strip()
        except Exception:
            return d

    def _cpu_pct(self):
        try:
            parts = open("/proc/stat").readline().split()
            vals = [int(x) for x in parts[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
            if self._prev_cpu:
                di = idle - self._prev_cpu[0]
                dt = total - self._prev_cpu[1]
                self._prev_cpu = (idle, total)
                if dt > 0:
                    return max(0, min(100, int(100 * (dt - di) / dt)))
            else:
                self._prev_cpu = (idle, total)
        except Exception:
            pass
        return self.cpu

    def _mem(self):
        try:
            d = {}
            for ln in open("/proc/meminfo"):
                k, _, v = ln.partition(":")
                d[k] = int(v.split()[0])
            tot = d["MemTotal"] // 1024
            avail = d.get("MemAvailable", d.get("MemFree", 0)) // 1024
            return tot - avail, tot
        except Exception:
            return self.mem_used, self.mem_total

    def _disk(self):
        try:
            st = os.statvfs("/")
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            total = st.f_blocks * st.f_frsize
            return int(100.0 * used / total) if total else 0
        except Exception:
            return self.disk_pct

    def _temp(self):
        # Zynq: XADC 经 hwmon 暴露; 板子也可能有别的路径
        import glob
        for p in (glob.glob("/sys/class/hwmon/hwmon*/temp1_input")
                  + glob.glob("/sys/class/thermal/thermal_zone*/temp")
                  + ["/sys/devices/soc0/amba/f8007100.adc/temp"]):
            v = self._read(p)
            if v:
                try:
                    t = float(v)
                    if t > 1000:
                        t /= 1000.0
                    if 0 < t < 150:
                        return t
                except Exception:
                    pass
        return self.temp

    def _wifi(self):
        """从 /sys 和 /proc 直接读, 不依赖额外工具

        ★ 踩过的坑: /proc/net/wireless 的格式是
             iface: status  quality  level  noise ...
          AIC8800 这个驱动把 **quality 报成 0**（所以之前一直显示 0%），
          但 **level 是真实 dBm**（例如 -32）。必须读第 3 列。
        """
        import glob
        import socket
        import struct
        try:
            import fcntl            # 只有 Linux 有; Windows 上预览时会缺
        except ImportError:
            fcntl = None
        for d in sorted(glob.glob("/sys/class/net/wl*")):
            try:
                if self._read(d + "/operstate", "down") != "up":
                    continue
                name = os.path.basename(d)[:15]
                ip = ""
                if fcntl is not None:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    try:
                        r = fcntl.ioctl(s.fileno(), 0x8915,
                                        struct.pack("256s", name.encode()))
                        ip = socket.inet_ntoa(r[20:24])
                    except Exception:
                        pass
                    s.close()
                # 信号: 优先 level(dBm); 读不到再退回 quality
                try:
                    for ln in open("/proc/net/wireless"):
                        if ln.strip().startswith(name):
                            f = ln.split(":", 1)[1].split()
                            lvl = float(f[2].rstrip("."))
                            if lvl < 0:
                                self.wifi_dbm = int(lvl)
                                # -30dBm≈满格, -90dBm≈没信号
                                self.wifi_qual = max(0, min(100,
                                                            int(2 * (lvl + 100))))
                            else:
                                q = float(f[1].rstrip("."))
                                self.wifi_qual = max(0, min(100, int(q / 70.0 * 100)))
                except Exception:
                    pass
                # ★ SSID 交给后台线程（带超时），界面只读缓存。
                #   早先这里用 os.popen("iw ...") 在 UI 线程里同步等子进程 ——
                #   AIC8800 驱动不稳时 iw 会阻塞，整个桌面就冻住（点哪都没反应）。
                self._kick_ssid(name)
                return self.wifi_ssid or "已连接", ip, self.wifi_qual, True
            except Exception:
                pass
        return self.wifi_ssid, self.wifi_ip, self.wifi_qual, False

    def _kick_ssid(self, name):
        """后台线程取 SSID（3 秒超时）。界面永远不在这里等。"""
        if self._ssid_busy or (time.time() - self._ssid_t) < 15:
            return
        self._ssid_busy = True
        self._ssid_t = time.time()

        def work():
            try:
                r = subprocess.run(["iw", "dev", name, "info"],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, timeout=3)
                m = re.search(rb"^\s*ssid\s+(\S.*)$", r.stdout or b"", re.M)
                if m:
                    self.wifi_ssid = m.group(1).decode("utf-8", "replace").strip()
            except Exception:
                pass
            finally:
                self._ssid_busy = False

        threading.Thread(target=work, name="ssid", daemon=True).start()

    # ---- 刷新 ----
    def _music_state(self):
        """首页音乐卡显示"正在播放什么"。

        播放器 (apps_music.py) 把状态写到 /tmp/zynq_music.json；
        这里只读一个小文件，不会阻塞界面。没有文件就保持空白
        （卡片会显示"还没有加音乐 / 把 .wav 放进 /home/zynq/Music"）。
        """
        try:
            import json
            with open("/tmp/zynq_music.json") as f:
                d = json.load(f)
        except Exception:
            return
        title = d.get("title") or ""
        if not title:
            self.music_title = ""
            self.music_playing = False
            return
        self.music_title = title
        self.music_playing = bool(d.get("playing"))
        self.music_pos = int(d.get("pos") or 0)
        self.music_len = int(d.get("len") or 0)

    def tick(self, force=False):
        now = time.time()
        self.t = time.localtime(now)
        self.dt = datetime.datetime.fromtimestamp(now)
        # 快刷（每秒）：时钟
        if force or now - self._last_fast > 1.0:
            self._last_fast = now
            self.cpu = self._cpu_pct()
            self._music_state()          # ★ 音乐卡跟着播放器走
            if force or now - self._last_full > 10.0:
                self._last_full = now
                self.mem_used, self.mem_total = self._mem()
                self.disk_pct = self._disk()
                self.temp = self._temp()
                s, ip, q, up = self._wifi()
                self.wifi_ssid, self.wifi_ip = s, ip
                self.wifi_qual, self.wifi_up = q, up
                self.weather = self._weather()
        return self

    def _weather(self):
        """读天气（缓存优先）。refresh() 是后台线程，绝不阻塞界面。"""
        try:
            import weather as _wx
            w = _wx.get_weather()
            w.refresh()
            d = w.get()
            if d:
                d = dict(d)
                d["age"] = w.age_str()
                return d
        except Exception:
            pass
        return self.weather


# =====================================================================
#  首页
# =====================================================================
class Home:
    def __init__(self, scr, info=None, apps=None, icons=None):
        self.scr = scr
        self.info = info or Info()
        self.apps = apps or []
        self.icons = icons or {}
        self.page = 0
        self.n_pages = 3
        self._glasses = {}
        self.static = None
        self._dirty_all = True
        self._parts = {}          # name -> [box, last_value]
        self._summoned = {}       # name -> draw 函数（画在当前 scr.img 上）
        self.rects = {}
        for key, c, r, cs, rs in CARDS:
            self.rects[key] = card_rect(c, r, cs, rs)
        self.dock = self._dock_rects()
        # 左侧空白处的"全部应用"按钮（Dock 之外的左半边空间）
        self.MENU_BTN = (26, self.dock["bar"][1], 196, self.dock["bar"][3])
        self.wall = None

    # ---------- 静态层 ----------
    def make_wallpaper(self):
        """渐变壁纸 + 两团柔光（本地生成，不依赖文件）"""
        from PIL import ImageChops
        im = Image.new("RGB", (W, H), C_BG_BOT)
        d = ImageDraw.Draw(im)
        for y in range(H):
            t = y / float(H - 1)
            d.line([(0, y), (W, y)],
                   fill=(int(C_BG_TOP[0] + (C_BG_BOT[0] - C_BG_TOP[0]) * t),
                         int(C_BG_TOP[1] + (C_BG_BOT[1] - C_BG_TOP[1]) * t),
                         int(C_BG_TOP[2] + (C_BG_BOT[2] - C_BG_TOP[2]) * t)))
        # 左上冷光 / 右下暖光: 低分辨率画好再放大 -> 天然柔和, 且快
        SW, SH = W // 8, H // 8
        ov = Image.new("RGB", (SW, SH), (0, 0, 0))
        od = ImageDraw.Draw(ov)
        for (cx, cy, rad, col) in ((-40, -30, 420, (40, 84, 190)),
                                   (W + 60, H + 40, 440, (96, 48, 140))):
            steps = 22
            for i in range(steps, 0, -1):
                rr = int(rad * i / steps / 8.0)
                a = (1.0 - i / float(steps)) ** 2.2
                ccx, ccy = cx // 8, cy // 8
                od.ellipse([ccx - rr, ccy - rr, ccx + rr, ccy + rr],
                           fill=(int(col[0] * a), int(col[1] * a), int(col[2] * a)))
        ov = ov.resize((W, H), Image.BILINEAR)
        return ImageChops.add(im, ov)

    def _glass(self, key, size, radius=CARD_R, alpha=0.87):
        """★ 按【尺寸】缓存，不按卡片缓存。

        6 张卡其实只有 2 种尺寸（480×242 和 234×242），原来每张卡各生成一张
        玻璃底图，等于白花 3 倍时间（2× 超采样遮罩 + LANCZOS 缩放 + 渐变都很贵）。
        """
        k = ("glass", size, radius, alpha)
        if k not in self._glasses:
            self._glasses[k] = fbui.glass(size, radius=radius, top=C_CARD_TOP,
                                          bot=C_CARD_BOT, alpha=alpha,
                                          border_a=26, gloss=14)
        return self._glasses[k]

    def _dock_icon(self, d, kind, cx, cy, s, col=(214, 224, 246)):
        """Dock 用的极简线性图标（自己画，不依赖字体里的符号）"""
        r = s / 2.0
        w = max(2, int(s * 0.11))
        if kind == "home":            # 四个方块 = 桌面
            g = s * 0.30
            for dx in (-1, 1):
                for dy in (-1, 1):
                    d.rectangle([cx + dx * g / 2 - g / 2.6, cy + dy * g / 2 - g / 2.6,
                                 cx + dx * g / 2 + g / 2.6, cy + dy * g / 2 + g / 2.6],
                                fill=col)
        elif kind == "apps":          # 3x3 点阵 = 应用
            for i in range(3):
                for j in range(3):
                    px = cx + (i - 1) * s * 0.32
                    py = cy + (j - 1) * s * 0.32
                    rr = s * 0.075
                    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=col)
        elif kind == "novel":         # 摊开的书
            d.rectangle([cx - r * 0.86, cy - r * 0.62, cx - r * 0.06, cy + r * 0.68],
                        outline=col, width=w)
            d.rectangle([cx + r * 0.06, cy - r * 0.62, cx + r * 0.86, cy + r * 0.68],
                        outline=col, width=w)
            d.line([cx, cy - r * 0.62, cx, cy + r * 0.68], fill=col, width=w)
        elif kind == "browser":       # 地球
            d.ellipse([cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82],
                      outline=col, width=w)
            d.ellipse([cx - r * 0.34, cy - r * 0.82, cx + r * 0.34, cy + r * 0.82],
                      outline=col, width=max(1, w - 1))
            d.line([cx - r * 0.82, cy, cx + r * 0.82, cy], fill=col, width=max(1, w - 1))
        elif kind == "music":         # 音符
            d.line([cx + r * 0.34, cy - r * 0.72, cx + r * 0.34, cy + r * 0.44],
                   fill=col, width=w)
            d.line([cx - r * 0.44, cy - r * 0.42, cx + r * 0.34, cy - r * 0.72],
                   fill=col, width=w)
            d.ellipse([cx - r * 0.86, cy + r * 0.20, cx - r * 0.06, cy + r * 0.82], fill=col)
        elif kind == "settings":      # 滑杆
            for k, yy in enumerate((-0.42, 0.42)):
                y = cy + r * yy
                d.line([cx - r * 0.86, y, cx + r * 0.86, y], fill=col, width=max(1, w - 1))
                px = cx + r * (0.34 if k == 0 else -0.30)
                d.ellipse([px - r * 0.26, y - r * 0.26, px + r * 0.26, y + r * 0.26], fill=col)

    def build_static(self):
        """把所有"不变的东西"画进一张图：壁纸 + 卡片底 + 卡片标题 + Dock"""
        im = (self.wall or self.make_wallpaper()).copy()
        # 卡片（含投影）
        for key, c, r, cs, rs in CARDS:
            x0, y0, x1, y1 = self.rects[key]
            w, h = x1 - x0, y1 - y0
            sh = self._glasses.get(("sh", w, h))
            if sh is None:
                sh = fbui.shadow((w, h), CARD_R, spread=22, alpha=70, offset=(0, 6))
                self._glasses[("sh", w, h)] = sh
            im.paste(sh, (x0 - 22, y0 - 22), sh)
            g = self._glass(key, (w, h))
            im.paste(g, (x0, y0), g)

        d = ImageDraw.Draw(im)
        f_t = fbui.font(14, cn=True)
        # 卡片标题（静态）
        for key, c, r, cs, rs in CARDS:
            x0, y0, x1, y1 = self.rects[key]
            title = {"clock": "", "weather": "天气", "system": "系统",
                     "music": "音乐", "network": "网络", "recent": "最近使用"}[key]
            if title:
                d.text((x0 + 18, y0 + 15), title, font=f_t, fill=C_TEXT_FAINT)
        # 状态栏底 + 分隔线
        d.rectangle([0, 0, W, STATUS_H - 1], fill=(12, 17, 30))
        d.line([(0, STATUS_H - 1), (W, STATUS_H - 1)], fill=(40, 52, 78))
        # Dock 玻璃条 + 投影
        dx0, dy0, dx1, dy1 = self.dock["bar"]
        dw, dh = dx1 - dx0, dy1 - dy0
        dsh = self._glasses.get(("shd", dw, dh))
        if dsh is None:
            dsh = fbui.shadow((dw, dh), DOCK_R, spread=22, alpha=86, offset=(0, 7))
            self._glasses[("shd", dw, dh)] = dsh
        im.paste(dsh, (dx0 - 22, dy0 - 22), dsh)
        g = self._glass("dock", (dw, dh), radius=DOCK_R, alpha=0.78)
        im.paste(g, (dx0, dy0), g)
        # Dock 图标 + 文字
        self._dock_content(d)
        self.static = im
        return im

    def _dock_content(self, d, label_font=None):
        """画 Dock 的 6 个图标 + 文字（build_static 和 draw_chrome 共用）"""
        f = label_font or fbui.font(13, cn=True)
        for i, (label, act) in enumerate(DOCK_ITEMS):
            bx0, by0, bx1, by1 = self.dock["items"][i]
            cx = (bx0 + bx1) / 2
            self._dock_icon(d, act, cx, by0 + 17, 22)
            tw = self.scr.tw(label, 13, cn=True)
            d.text((cx - tw / 2, by0 + 31), label, font=f, fill=C_TEXT_DIM)

    def build_static_plain(self):
        """降级样式: 万一玻璃材质生成失败(老 Pillow), 也不能让首页起不来"""
        im = (self.wall or self.make_wallpaper()).copy()
        d = ImageDraw.Draw(im)
        for key, c, r, cs, rs in CARDS:
            x0, y0, x1, y1 = self.rects[key]
            d.rectangle([x0, y0, x1, y1], fill=C_CARD_BOT, outline=(70, 86, 120))
            d.text((x0 + 18, y0 + 15),
                   {"clock": "现在", "weather": "天气", "system": "系统",
                    "music": "音乐", "network": "网络", "recent": "最近使用"}[key],
                   font=fbui.font(14, cn=True), fill=C_TEXT_FAINT)
        d.rectangle([0, 0, W, STATUS_H - 1], fill=(12, 17, 30))
        dx0, dy0, dx1, dy1 = self.dock["bar"]
        d.rectangle([dx0, dy0, dx1, dy1], fill=(18, 24, 40), outline=(70, 86, 120))
        self._dock_content(d)
        self.static = im
        return im

    def _menu_button(self, scr):
        """左侧的"全部应用"按钮（图标页上用它打开开始菜单）"""
        x0, y0, x1, y1 = self.MENU_BTN
        scr.rrect([x0, y0, x1, y1], 20, fill=(24, 31, 52), outline=(52, 66, 96), width=1)
        cy = (y0 + y1) // 2
        d = scr.d
        for k in range(3):
            yy = cy - 7 + k * 7
            d.line([x0 + 20, yy, x0 + 46, yy], fill=C_TEXT_DIM, width=2)
        scr.text((x0 + 58, cy), "全部应用", 16, C_TEXT_DIM, cn=True, anchor="lm")

    def draw_chrome(self, scr, menu_btn=True):
        """在【任意页】画顶部状态栏 + 底部 Dock + 页码点（图标页也复用这套外壳）"""
        if self.static is None:
            self.build_static()
        scr.d.rectangle([0, 0, W, STATUS_H - 1], fill=(12, 17, 30))
        scr.d.line([(0, STATUS_H - 1), (W, STATUS_H - 1)], fill=(40, 52, 78))
        dx0, dy0, dx1, dy1 = self.dock["bar"]
        dw, dh = dx1 - dx0, dy1 - dy0
        sh = self._glasses.get(("shd", dw, dh))
        if sh is None:
            sh = fbui.shadow((dw, dh), DOCK_R, spread=22, alpha=86, offset=(0, 7))
            self._glasses[("shd", dw, dh)] = sh
        scr.img.paste(sh, (dx0 - 22, dy0 - 22), sh)
        g = self._glass("dock", (dw, dh), radius=DOCK_R, alpha=0.78)
        scr.img.paste(g, (dx0, dy0), g)
        self._dock_content(scr.d)
        if menu_btn:
            self._menu_button(scr)
        self.draw_status()
        self.draw_dots()

    def _dock_rects(self):
        n = len(DOCK_ITEMS)
        iw = 88
        bw = n * iw + 24
        bx0 = (W - bw) // 2
        by0 = H - DOCK_H + 8
        by1 = by0 + 56
        items = []
        for i in range(n):
            x = bx0 + 12 + i * iw
            items.append((x, by0, x + iw, by1))
        return {"bar": (bx0, by0, bx0 + bw, by1), "items": items}

    # ---------- 动态层 ----------
    def _reg(self, name, box):
        """注册一个"值会变"的区域。box 是重画范围。"""
        self._parts[name] = [box, None]

    def _val(self):
        i = self.info
        d = i.dt
        return {
            "clock_time": d.strftime("%H:%M"),
            "clock_greet": ("凌晨好" if d.hour < 6 else "早上好" if d.hour < 11
                            else "中午好" if d.hour < 13 else "下午好" if d.hour < 18
                            else "晚上好"),
            "clock_date": d.date(),
            "clock_ring": d.second,
            "system": (i.cpu, i.mem_used, i.disk_pct, None if i.temp is None else int(i.temp)),
            "weather": None if not i.weather else (
                i.weather.get("temp"), i.weather.get("text"), i.weather.get("city"),
                i.weather.get("kind"), i.weather.get("age")),
            "music": (i.music_title, i.music_playing, i.music_pos, i.music_len),
            "network": (i.wifi_ssid, i.wifi_ip, i.wifi_qual, i.wifi_up, i.wifi_dbm),
            "recent": tuple(a["name"] for a in self.apps[:4]),
            "status": (i.cpu, i.mem_used, None if i.temp is None else int(i.temp),
                       i.wifi_ssid, i.wifi_up, d.strftime("%H:%M:%S")),
            "dots": self.page,
        }

    def register_parts(self):
        x0, y0, x1, y1 = self.rects["clock"]
        self._reg("clock_greet", (x0 + 16, y0 + 8, x0 + 140, y0 + 36))
        self._reg("clock_time", (x0 + 16, y0 + 30, x1 - 16, y0 + 168))
        self._reg("clock_date", (x0 + 16, y0 + 170, x1 - 16, y1 - 12))
        self._reg("clock_ring", (x0 + 338, y0 + 62, x0 + 448, y0 + 176))

        x0, y0, x1, y1 = self.rects["weather"]
        self._reg("weather", (x0 + 16, y0 + 34, x1 - 16, y1 - 16))

        x0, y0, x1, y1 = self.rects["system"]
        self._reg("system", (x0 + 16, y0 + 34, x1 - 16, y1 - 14))

        x0, y0, x1, y1 = self.rects["music"]
        self._reg("music", (x0 + 16, y0 + 34, x1 - 16, y1 - 14))

        x0, y0, x1, y1 = self.rects["network"]
        self._reg("network", (x0 + 16, y0 + 34, x1 - 16, y1 - 14))

        x0, y0, x1, y1 = self.rects["recent"]
        self._reg("recent", (x0 + 16, y0 + 34, x1 - 16, y1 - 14))

        self._reg("status", (0, 0, W, STATUS_H))
        self._reg("dots", (self.dock["bar"][2] + 8, self.dock["bar"][1],
                           W, self.dock["bar"][3]))

    # ---- 各区域画法（画在 scr.img 上，坐标用绝对坐标）----
    def draw_clock_time(self):
        x0, y0, x1, y1 = self.rects["clock"]
        t = self.info.dt.strftime("%H:%M")
        self.scr.text((x0 + 26, y0 + 52), t, 96, C_TEXT, bold=True)

    def draw_clock_greet(self):
        """问候语放在卡片标题的位置（原来是"现在"）"""
        x0, y0, x1, y1 = self.rects["clock"]
        h = self.info.dt.hour
        greet = ("凌晨好" if h < 6 else "早上好" if h < 11 else "中午好" if h < 13
                 else "下午好" if h < 18 else "晚上好")
        self.scr.text((x0 + 30, y0 + 16), greet, 16, C_ACCENT, cn=True)

    def draw_clock_date(self):
        x0, y0, x1, y1 = self.rects["clock"]
        d = self.info.dt
        wd = "周" + "一二三四五六日"[d.weekday()]
        self.scr.text((x0 + 30, y0 + 188), "%d年%d月%d日  %s" % (d.year, d.month, d.day, wd),
                      20, C_TEXT_DIM, cn=True)

    def draw_clock_ring(self):
        """右侧秒针环 —— 每秒都在动, 让首页"活着" """
        x0, y0, x1, y1 = self.rects["clock"]
        cx, cy, r = x0 + 392, y0 + 118, 46
        d = self.scr.d
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(46, 58, 86), width=5)
        sec = self.info.dt.second
        if sec > 0:
            d.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + int(360 * sec / 60.0),
                  fill=C_ACCENT, width=5)
        day = self.info.dt.day
        self.scr.text((cx, cy - 2), str(day), 34, C_TEXT, bold=True, anchor="mm")
        self.scr.text((cx, cy + 24), "秒 %02d" % sec, 12, C_TEXT_FAINT, cn=True, anchor="mm")

    def _album_art(self, x, y, s, playing=True):
        """专辑封面占位: 圆角渐变 + 音符"""
        d = self.scr.d
        self.scr.rrect([x, y, x + s, y + s], 16,
                       fill=(58, 74, 132) if playing else (40, 48, 70))
        if playing:
            for i in range(s - 2, 0, -1):
                t = i / float(s)
                if i % 2:
                    continue
                col = (int(76 + 90 * (1 - t)), int(90 + 40 * t), int(200 + 40 * t))
                self.scr.rrect([x + (s - i) // 2, y + (s - i) // 2,
                                x + (s + i) // 2, y + (s + i) // 2], max(2, 16 - i // 6),
                               fill=col)
        w = max(3, s // 16)
        cx, cy, r = x + s / 2, y + s / 2, s * 0.20
        d.line([cx + r * 0.5, cy - r * 1.3, cx + r * 0.5, cy + r * 0.75],
               fill=(255, 255, 255), width=w)
        d.line([cx - r * 0.85, cy - r * 0.75, cx + r * 0.5, cy - r * 1.3],
               fill=(255, 255, 255), width=w)
        d.ellipse([cx - r * 1.5, cy + r * 0.35, cx - r * 0.1, cy + r * 1.35],
                  fill=(255, 255, 255))

    def _sun(self, cx, cy, r):
        d = self.scr.d
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 196, 60))
        for k in range(8):
            a = math.radians(k * 45)
            x1 = cx + int((r + 8) * math.cos(a)); y1 = cy + int((r + 8) * math.sin(a))
            x2 = cx + int((r + 17) * math.cos(a)); y2 = cy + int((r + 17) * math.sin(a))
            d.line([(x1, y1), (x2, y2)], fill=(255, 196, 60), width=3)

    def _wicon(self, kind, cx, cy, r):
        """按天气类型画图标（晴/多云/阴/雨/雪/雷/雾）"""
        d = self.scr.d
        if kind == "sun":
            self._sun(cx, cy, r)
            return
        cloud = (206, 214, 232)
        shift = 0
        if kind in ("cloud", "rain", "snow", "storm", "sleet", "fog"):
            if kind != "fog":
                # 云 = 三个圆 + 一条底边
                d.ellipse([cx - r, cy - r * 0.2, cx + r * 0.2, cy + r * 0.9], fill=cloud)
                d.ellipse([cx - r * 0.35, cy - r * 0.85, cx + r * 0.75, cy + r * 0.5], fill=cloud)
                d.ellipse([cx + r * 0.05, cy - r * 0.1, cx + r * 1.05, cy + r * 0.85], fill=cloud)
                d.rectangle([cx - r * 0.9, cy + r * 0.35, cx + r * 0.95, cy + r * 0.85],
                            fill=cloud)
                shift = -r * 0.25
            else:
                for k in (-0.55, 0.0, 0.55):
                    yy = cy + r * k
                    d.line([cx - r * 1.15, yy, cx + r * 1.15, yy], fill=cloud,
                           width=max(2, int(r * 0.22)))
                return
        col = {"rain": (110, 190, 255), "sleet": (150, 210, 255),
               "snow": (235, 245, 255), "storm": (255, 214, 60)}.get(kind)
        if kind == "storm":
            z = r * 0.75
            cy2 = cy + r * 0.9
            d.polygon([(cx + z * 0.18, cy2 - z * 0.55), (cx - z * 0.55, cy2 + z * 0.35),
                       (cx - z * 0.05, cy2 + z * 0.35), (cx - z * 0.22, cy2 + z * 1.05),
                       (cx + z * 0.55, cy2 + z * 0.05), (cx + z * 0.05, cy2 + z * 0.05)],
                      fill=col)
        elif kind in ("rain", "sleet"):
            for k in (-0.55, 0.0, 0.55):
                x1 = cx + r * k
                d.line([x1, cy + r * 0.95, x1 - r * 0.25, cy + r * 1.75], fill=col,
                       width=max(2, int(r * 0.16)))
            if kind == "sleet":
                for k in (-0.35, 0.35):
                    d.ellipse([cx + r * k - 2, cy + r * 1.85, cx + r * k + 2, cy + r * 1.95],
                              fill=(235, 245, 255))
        elif kind == "snow":
            for k in (-0.55, 0.0, 0.55):
                px, py = cx + r * k, cy + r * 1.35
                d.line([px - 4, py, px + 4, py], fill=col, width=2)
                d.line([px, py - 4, px, py + 4], fill=col, width=2)

    def draw_weather(self):
        x0, y0, x1, y1 = self.rects["weather"]
        w = self.info.weather
        if not w:
            cx = (x0 + x1) // 2
            self.scr.text((cx, (y0 + y1) // 2 - 26), "未联网", 24, C_TEXT_DIM,
                          cn=True, anchor="mm")
            self.scr.text((cx, (y0 + y1) // 2 + 8), "点这里设置 WiFi", 14, C_TEXT_FAINT,
                          cn=True, anchor="mm")
            return
        self._wicon(w.get("kind") or "sun", x0 + 44, y0 + 74, 20)
        self.scr.text((x0 + 78, y0 + 46), "%d°" % w.get("temp", 0), 54, C_TEXT, bold=True)
        self.scr.text((x0 + 26, y0 + 132), w.get("text", ""), 22, C_TEXT_DIM, cn=True)
        self.scr.text((x1 - 26, y0 + 134), w.get("city", ""), 16, C_TEXT_FAINT,
                      cn=True, anchor="rm")
        line = "最高 %d°  最低 %d°" % (w.get("hi", 0), w.get("lo", 0))
        if w.get("hum"):
            line += "  湿%d%%" % w["hum"]
        self.scr.text((x0 + 26, y0 + 174), line, 13, C_TEXT_FAINT, cn=True)
        if w.get("age"):
            self.scr.text((x1 - 26, y1 - 28), w["age"], 12, C_TEXT_FAINT,
                          cn=True, anchor="rm")

    def draw_system(self):
        x0, y0, x1, y1 = self.rects["system"]
        i = self.info
        rows = [("CPU", "%d%%" % i.cpu, i.cpu, C_ACCENT),
                ("内存", "%dM" % i.mem_used,
                 int(100.0 * i.mem_used / i.mem_total) if i.mem_total else 0, C_OK),
                ("存储", "%d%%" % i.disk_pct, i.disk_pct, (180, 150, 250))]
        yy = y0 + 46
        for (lab, val, pct, col) in rows:
            self.scr.text((x0 + 18, yy), lab, 16, C_TEXT_DIM, cn=True)
            self.scr.text((x1 - 18, yy - 2), val, 17, C_TEXT, cn=True,
                          anchor="rm", bold=True)
            bx0, bx1 = x0 + 18, x1 - 18
            self.scr.rrect([bx0, yy + 26, bx1, yy + 33], 4, fill=C_BAR_BG)
            fw = int((bx1 - bx0) * max(0, min(100, pct)) / 100.0)
            if fw > 0:
                self.scr.rrect([bx0, yy + 26, bx0 + fw, yy + 33], 4, fill=col)
            yy += 60
        if i.temp is not None:
            self.scr.text((x0 + 18, y1 - 32), "PL 温度 %d°C" % i.temp, 14,
                          C_TEXT_FAINT, cn=True)

    def draw_music(self):
        x0, y0, x1, y1 = self.rects["music"]
        i = self.info
        playing = bool(i.music_title)
        self._album_art(x0 + 22, y0 + 44, 106, playing)
        tx = x0 + 146
        if not playing:
            self.scr.text((tx, y0 + 62), "还没有加音乐", 24, C_TEXT_DIM, cn=True)
            self.scr.text((tx, y0 + 100), "把 .wav / .mp3 放进 /home/zynq/Music",
                          14, C_TEXT_FAINT, cn=True)
        else:
            self.scr.text((tx, y0 + 54), i.music_title, 24, C_TEXT, cn=True)
            if i.music_artist:
                self.scr.text((tx, y0 + 94), i.music_artist, 15, C_TEXT_FAINT, cn=True)
        self._play_buttons(x0 + 22, y1 - 66, i.music_playing, i.music_pos, i.music_len)

    def _play_buttons(self, x, y, playing, pos, ln):
        bw, bh, gp = 52, 44, 14
        d = self.scr.d
        for k in range(3):
            bx = x + k * (bw + gp)
            col = C_ACCENT if k == 1 else (58, 78, 122)
            self.scr.rrect([bx, y, bx + bw, y + bh], 13, fill=col)
            cx, cy = bx + bw // 2, y + bh // 2
            if k == 0:
                d.polygon([(cx + 6, cy - 9), (cx + 6, cy + 9), (cx - 6, cy)], fill=(235, 240, 255))
                d.rectangle([cx - 10, cy - 9, cx - 7, cy + 9], fill=(235, 240, 255))
            elif k == 2:
                d.polygon([(cx - 6, cy - 9), (cx - 6, cy + 9), (cx + 6, cy)], fill=(235, 240, 255))
                d.rectangle([cx + 7, cy - 9, cx + 10, cy + 9], fill=(235, 240, 255))
            elif playing:
                d.rectangle([cx - 7, cy - 9, cx - 2, cy + 9], fill=(255, 255, 255))
                d.rectangle([cx + 2, cy - 9, cx + 7, cy + 9], fill=(255, 255, 255))
            else:
                d.polygon([(cx - 6, cy - 10), (cx - 6, cy + 10), (cx + 9, cy)], fill=(255, 255, 255))
        # 进度条（按钮右侧）
        px0 = x + 3 * (bw + gp) + 20
        px1 = self.rects["music"][2] - 22
        py = y + bh // 2 + 8
        self.scr.rrect([px0, py - 3, px1, py + 3], 3, fill=C_BAR_BG)
        if ln > 0:
            fw = int((px1 - px0) * min(1.0, pos / float(ln)))
            if fw > 0:
                self.scr.rrect([px0, py - 3, px0 + fw, py + 3], 3, fill=C_ACCENT)
        self.scr.text((px1, py - 22), "%d:%02d / %d:%02d" % (pos // 60, pos % 60,
                                                             ln // 60, ln % 60),
                      13, C_TEXT_FAINT, mono=True, anchor="rm")

    def draw_network(self):
        x0, y0, x1, y1 = self.rects["network"]
        i = self.info
        cy = y0 + 76
        col = C_OK if i.wifi_up else C_TEXT_FAINT
        d = self.scr.d
        for rr in (10, 17, 24):
            d.arc([x0 + 26 - rr, cy - rr + 10, x0 + 26 + rr, cy + rr + 10],
                  200, 340, fill=col, width=4)
        d.ellipse([x0 + 23, cy + 6, x0 + 29, cy + 12], fill=col)
        self.scr.text((x0 + 64, cy - 26), i.wifi_ssid or "未连接", 17, C_TEXT, cn=True)
        self.scr.text((x0 + 64, cy + 2), i.wifi_ip or "-", 14, C_TEXT_FAINT, mono=True)
        bx0, bx1 = x0 + 18, x1 - 18
        by = y1 - 46
        self.scr.rrect([bx0, by, bx1, by + 6], 3, fill=C_BAR_BG)
        fw = int((bx1 - bx0) * i.wifi_qual / 100.0)
        if fw > 0:
            self.scr.rrect([bx0, by, bx0 + fw, by + 6], 3, fill=col)
        lbl = ("已连接 · %d%% · %ddBm" % (i.wifi_qual, i.wifi_dbm)
               if i.wifi_up else "未连接")
        self.scr.text((bx0, by + 14), lbl, 13, C_TEXT_FAINT, cn=True)

    RECENT_S = 48                 # 「最近使用」卡片里图标的边长

    def recent_centers(self):
        """「最近使用」卡片里 4 个应用图标的**中心**。

        ★ 画图标和判定点击必须用同一份坐标。之前 draw_recent 用
          (+60,+76 / 步进 114,88)，而 hit() 里另写了一套 (+34,+60 / 84,82)，
          结果右边那一列两个图标点不到（图标在 x=938，判定窗口只到 908）。
        """
        x0, y0, x1, y1 = self.rects["recent"]
        return [(x0 + 60 + (k % 2) * 114, y0 + 76 + (k // 2) * 88)
                for k in range(4)]

    def draw_recent(self):
        x0, y0, x1, y1 = self.rects["recent"]
        names = [a["name"] for a in self.apps[:4]]
        if not names:
            names = ["扫雷", "计算器", "画板", "文件"]
        tint = {a["name"]: a.get("tint", (90, 130, 200)) for a in self.apps}
        s = self.RECENT_S
        f = fbui.font(12, cn=True)
        for k, n in enumerate(names):
            cx, cy = self.recent_centers()[k]
            col = tint.get(n, (90, 130, 200))
            self.scr.rrect([cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2], 14, fill=col)
            ic = self.icons.get(n)
            if ic:
                try:
                    ic(self.scr.d, cx - (s - 20) / 2, cy - (s - 20) / 2, s - 20)
                except Exception:
                    pass
            tw = self.scr.tw(n, 12, cn=True)
            self.scr.d.text((cx - tw / 2, cy + s // 2 + 6), n, font=f, fill=C_TEXT_DIM)

    def draw_status(self):
        i = self.info
        y = STATUS_H // 2
        col = C_OK if i.wifi_up else C_TEXT_FAINT
        self.scr.d.ellipse([14, y - 4, 22, y + 4], fill=col)
        self.scr.text((28, y), (i.wifi_ssid or "未连接"), 13, C_TEXT_DIM, cn=True, anchor="lm")
        seg = []
        seg.append("CPU %d%%" % i.cpu)
        seg.append("RAM %dM" % i.mem_used)
        if i.temp is not None:
            seg.append("%d°C" % i.temp)
        self.scr.text((W // 2, y), "   ".join(seg), 13, C_TEXT_DIM, cn=True, anchor="mm")
        self.scr.text((W - 14, y), i.dt.strftime("%Y-%m-%d  %H:%M:%S"), 13,
                      C_TEXT_DIM, mono=True, anchor="rm")

    def draw_dots(self):
        x0, y0, x1, y1 = self.dock["bar"]
        d = self.scr.d
        cy = (y0 + y1) // 2
        n = self.n_pages
        start = x1 + 26
        for k in range(n):
            cx = start + k * 22
            r = 5 if k == self.page else 4
            col = C_TEXT if k == self.page else (86, 100, 130)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    # ---------- 主绘制 ----------
    def draw(self, full=False):
        scr = self.scr
        self.info.tick()
        if self.static is None:
            try:
                self.build_static()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                print("卡片静态层生成失败, 用降级样式:", ex)
                self.build_static_plain()
            self.register_parts()
            full = True
        vals = self._val()
        fns = {
            "clock_greet": self.draw_clock_greet, "clock_time": self.draw_clock_time,
            "clock_date": self.draw_clock_date, "clock_ring": self.draw_clock_ring,
            "weather": self.draw_weather, "system": self.draw_system,
            "music": self.draw_music, "network": self.draw_network,
            "recent": self.draw_recent, "status": self.draw_status,
            "dots": self.draw_dots,
        }
        if full:
            scr.img.paste(self.static, (0, 0))
            for name in self._parts:
                fns[name]()
                self._parts[name][1] = vals.get(name)
            scr.flush()
            return len(self._parts)
        # 只重画"值变了"的那几个小方框
        n = 0
        for name, st in self._parts.items():
            v = vals.get(name)
            if v == st[1]:
                continue
            st[1] = v
            box = st[0]
            b = (box[0], box[1], box[2], box[3])
            # ★ PIL 的 paste(im, box, mask) 第三个参数是 mask, 不是"源区域"。
            #   要拷一块区域必须自己 crop 再贴。
            scr.img.paste(self.static.crop(b), (b[0], b[1]))
            fns[name]()
            scr.flush(box)
            n += 1
        return n

    # ---------- 交互 ----------
    def restore(self, box):
        """把一块区域还原成"静态层 + 最新动态内容"（临时浮层 toast 用完后收尾）"""
        scr = self.scr
        if self.static is None:
            self.build_static()
            self.register_parts()
        b = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))
        scr.img.paste(self.static.crop(b), (b[0], b[1]))
        for name, st in self._parts.items():
            r = st[0]
            if not (r[2] < b[0] or r[0] > b[2] or r[3] < b[1] or r[1] > b[3]):
                st[1] = None          # 强制重画
        self.draw()
        scr.flush(b)

    def hit(self, x, y):
        """返回动作 ('app', 名字) / ('card', key) / ('dock', act) / ('page', n) / ('menu', None)"""
        if fbui.hit(self.MENU_BTN, x, y):
            return ("menu", None)
        for i, (label, act) in enumerate(DOCK_ITEMS):
            if fbui.hit(self.dock["items"][i], x, y):
                return ("dock", act)
        bx0, by0, bx1, by1 = self.dock["bar"]
        cy = (by0 + by1) // 2
        for k in range(self.n_pages):
            cx = bx1 + 26 + k * 22
            if abs(x - cx) <= 11 and abs(y - cy) <= 11:
                return ("page", k)
        for key, c, r, cs, rs in CARDS:
            if fbui.hit(self.rects[key], x, y):
                if key == "recent":
                    # ★ 和 draw_recent() 用同一份坐标（以前这里另写了一套，
                    #   右边一列两个图标点不到）
                    names = [a["name"] for a in self.apps[:4]]
                    rad = self.RECENT_S // 2 + 6
                    for k, nm in enumerate(names):
                        cx, cyy = self.recent_centers()[k]
                        if abs(x - cx) <= rad and abs(y - cyy) <= rad:
                            return ("app", nm)
                return ("card", key)
        return None
