#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_clock.py —— 时钟：多个【会动】的表盘，可自由切换（参考 iOS 时钟）

四个表盘（点 ◀ ▶ 或点表盘名切换）：
  1. 数字   —— 大号数字钟，秒在走，底部一条走秒进度线
  2. 指针   —— 圆形表盘，时/分/秒针连续平滑走动（iOS 世界时钟的样式）
  3. 世界   —— 六个城市，每个一个小表盘 + 城市名 + 数字时间
  4. 秒表   —— 模拟表盘 + 大号数字，支持 开始/停止/复位

★ 动画说明：
    桌面主循环(desktop.py)只在有触摸事件时重绘，但 App 自己的 run()
    是每轮都重绘的，所以这里能逐帧动。
★ 省带宽：只 flush 需要更新的那块区域。
"""
import math
import time

from fbui import header, back_hit, btn, hit

# ── iOS 风格配色 ──────────────────────────────────────────────
C_BG      = (0, 0, 0)
C_TEXT    = (255, 255, 255)
C_DIM     = (134, 134, 134)
C_FAINT   = (75, 75, 75)
C_ORANGE  = (255, 149, 0)          # iOS 秒针/强调色
C_GREEN   = (48, 209, 88)          # 秒表开始
C_RED     = (255, 69, 58)          # 秒表停止
C_GREY_BT = (58, 58, 60)           # 按钮底
C_FACE    = (22, 22, 24)           # 表盘底

FACES = ("数字", "指针", "世界", "秒表")

# 城市（当前夏令时偏移，单位小时；板子已设成 Asia/Shanghai）
CITIES = (
    ("北京",   8), ("东京",   9), ("悉尼",  10),
    ("伦敦",   1), ("纽约",  -4), ("洛杉矶", -7),
)

# 表盘/按钮布局
CLOCK_CX, CLOCK_CY = 512, 292      # 主表盘中心
CLOCK_R = 186                       # 主表盘半径
BTN_Y = 512                         # 底部按钮条


def _hms(t):
    lt = time.localtime(t)
    return lt.tm_hour, lt.tm_min, lt.tm_sec


def draw_analog(scr, cx, cy, R, t, tick=True, smooth=True, hand_len=1.0):
    """画一个圆形指针表盘。返回它的包围盒（用于局部 flush）。

    smooth=True 时，秒针连续走动（不是一秒一跳）。
    """
    d = scr.d
    lt = time.localtime(t)
    frac = t - int(t)
    sec = (lt.tm_sec + (frac if smooth else 0)) % 60
    minute = lt.tm_min + sec / 60.0
    hour = (lt.tm_hour % 12) + minute / 60.0

    # 外圈
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=C_FACE,
              outline=(44, 46, 52), width=2)

    if tick:
        # 60 个刻度；整点粗、其余细
        for i in range(60):
            a = math.radians(i * 6 - 90)
            major = (i % 5 == 0)
            r1 = R * (0.86 if major else 0.92)
            r2 = R * 0.96
            col = C_TEXT if major else C_FAINT
            d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                    cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
                   fill=col, width=3 if major else 1)

    def hand(angle_deg, length, width, color, tail=0.0):
        a = math.radians(angle_deg - 90)
        ca, sa = math.cos(a), math.sin(a)
        d.line([cx - ca * R * tail, cy - sa * R * tail,
                cx + ca * R * length, cy + sa * R * length],
               fill=color, width=width)

    # 时针（短粗）
    hand(hour * 30, 0.46 * hand_len, max(4, int(R * 0.045)), C_TEXT, tail=0.06)
    # 分针（长一点）
    hand(minute * 6, 0.68 * hand_len, max(3, int(R * 0.030)), C_TEXT, tail=0.08)
    # 秒针（细，橙色，带尾巴 —— iOS 风格）
    hand(sec * 6, 0.82 * hand_len, max(2, int(R * 0.014)), C_ORANGE, tail=0.14)
    # 中心轴
    r = max(3, int(R * 0.035))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C_ORANGE)
    return [cx - R - 3, cy - R - 3, cx + R + 3, cy + R + 3]


# ── 表盘 1：数字 ─────────────────────────────────────────────
def draw_digital(scr, t, box):
    h, m, s = _hms(t)
    d = scr.d
    d.rectangle(box, fill=C_BG)
    cx = (box[0] + box[2]) // 2

    # 大号 HH:MM
    scr.text((cx, 250), "%02d:%02d" % (h, m), 168, C_TEXT,
             anchor="mm", mono=True)
    # 秒（小一号，跟在右下）
    scr.text((cx, 372), "%02d" % s, 44, C_ORANGE, anchor="mm", mono=True)
    scr.text((cx + 62, 378), "秒", 22, C_DIM, anchor="lm", cn=True)

    lt = time.localtime(t)
    wd = "一二三四五六日"[lt.tm_wday]
    scr.text((cx, 432), "%d 年 %d 月 %d 日  星期%s" %
             (lt.tm_year, lt.tm_mon, lt.tm_mday, wd), 24, C_DIM,
             anchor="mm", cn=True)

    # 走秒进度线（★ 用 fbui 的 scr.rrect：
    #   板上 PIL 太老，ImageDraw 没有 rounded_rectangle，只有 PIL>=8.2 才有）
    x0, x1, yy = cx - 300, cx + 300, 470
    scr.rrect([x0, yy, x1, yy + 6], 3, fill=C_FAINT)
    fw = int((x1 - x0) * (s + (t - int(t))) / 60.0)
    if fw > 0:
        scr.rrect([x0, yy, x0 + fw, yy + 6], 3, fill=C_ORANGE)
    return [box[0], 150, box[2], 490]


# ── 表盘 2：指针（大表盘）────────────────────────────────────
def draw_pointer(scr, t, box):
    scr.clear(C_BG)
    scr.d.rectangle(box, fill=C_BG)
    r = draw_analog(scr, CLOCK_CX, CLOCK_CY - 24, CLOCK_R, t)
    lt = time.localtime(t)
    scr.text((CLOCK_CX, 480), "%02d:%02d:%02d" %
             (lt.tm_hour, lt.tm_min, lt.tm_sec), 34, C_DIM,
             anchor="mm", mono=True)
    return [box[0], box[1], box[2], box[3]]


# ── 表盘 3：世界时钟 ─────────────────────────────────────────
def draw_world(scr, t, box):
    scr.d.rectangle(box, fill=C_BG)
    utc = time.gmtime(t)
    base = utc.tm_hour * 3600 + utc.tm_min * 60 + utc.tm_sec
    # 3 列 × 2 行
    for i, (city, off) in enumerate(CITIES):
        col, row = i % 3, i // 3
        cx = 190 + col * 322
        cy = 190 + row * 200
        secs = (base + off * 3600) % 86400
        hh, mm = secs // 3600, (secs % 3600) // 60
        ss = secs % 60

        # 小表盘（用假的 localtime 时间驱动指针）
        fake = time.mktime((2000, 1, 1, int(hh), int(mm), int(ss),
                            0, 0, -1))
        draw_analog(scr, cx, cy, 62, fake + (t - int(t)),
                    tick=True, smooth=True)

        scr.text((cx, cy + 82), city, 22, C_TEXT, anchor="mm", cn=True)
        scr.text((cx, cy + 110), "%02d:%02d" % (hh, mm), 20, C_DIM,
                 anchor="mm", mono=True)
        scr.text((cx + 78, cy + 112), "%02d" % ss, 15, C_ORANGE,
                 anchor="lm", mono=True)
    return [box[0], box[1], box[2], box[3]]


# ── 表盘 4：秒表 ─────────────────────────────────────────────
class Stopwatch(object):
    def __init__(self):
        self.t0 = None
        self.acc = 0.0

    def elapsed(self):
        if self.t0 is None:
            return self.acc
        return self.acc + (time.time() - self.t0)

    def start(self):
        if self.t0 is None:
            self.t0 = time.time()

    def stop(self):
        if self.t0 is not None:
            self.acc += time.time() - self.t0
            self.t0 = None

    def reset(self):
        self.t0 = None
        self.acc = 0.0

    def running(self):
        return self.t0 is not None


def draw_stopwatch(scr, sw, box):
    scr.d.rectangle(box, fill=C_BG)
    el = sw.elapsed()
    cx, cy, R = CLOCK_CX, 250, 150

    # 模拟盘：秒针 60 秒一圈，分针 30 分钟一圈
    d = scr.d
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=C_FACE,
              outline=(44, 46, 52), width=2)
    for i in range(60):
        a = math.radians(i * 6 - 90)
        major = (i % 5 == 0)
        r1 = R * (0.86 if major else 0.92)
        r2 = R * 0.96
        d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
               fill=C_TEXT if major else C_FAINT, width=3 if major else 1)

    def hand(angle_deg, length, width, color, tail=0.0):
        a = math.radians(angle_deg - 90)
        ca, sa = math.cos(a), math.sin(a)
        d.line([cx - ca * R * tail, cy - sa * R * tail,
                cx + ca * R * length, cy + sa * R * length],
               fill=color, width=width)

    hand((el % 60) * 6, 0.84, 3, C_ORANGE, tail=0.14)          # 秒
    hand(((el / 60.0) % 30) * 12, 0.60, 4, C_TEXT, tail=0.08)   # 分
    r = 5
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C_ORANGE)

    # 数字
    mm = int(el) // 60
    ss = int(el) % 60
    cs = int((el - int(el)) * 100)
    scr.text((cx, 448), "%02d:%02d.%02d" % (mm, ss, cs), 62, C_TEXT,
             anchor="mm", mono=True)
    return [box[0], box[1], box[2], box[3]]


# ── 主循环 ───────────────────────────────────────────────────
def run(scr, touch):
    face = 0
    sw = Stopwatch()
    last = 0.0
    dirty = None

    while True:
        now = time.time()

        # 数字表盘每秒才需要重画；其它表盘平滑动画
        if face == 0:
            if now - last < 0.2:
                time.sleep(0.02)
                continue
        elif now - last < 0.05:          # ~20fps
            time.sleep(0.01)
            continue
        last = now

        # 顶部：标题 + 表盘切换
        scr.clear(C_BG)
        header(scr, "时钟")
        bx = 36
        for i, nm in enumerate(FACES):
            w = scr.tw(nm, 17, cn=True) + 30
            r = [bx, 62, bx + w, 96]
            on = (i == face)
            btn(scr, r, nm, fill=(255, 149, 0) if on else C_GREY_BT,
                size=17, cn=True, radius=8,
                tc=(0, 0, 0) if on else C_TEXT)
            if i == face:
                face_rect = r
            bx += w + 8

        body = [0, 104, 1024, 500]
        if face == 0:
            dirty = draw_digital(scr, now, body)
        elif face == 1:
            dirty = draw_pointer(scr, now, body)
        elif face == 2:
            dirty = draw_world(scr, now, body)
        else:
            dirty = draw_stopwatch(scr, sw, body)

        # 秒表按钮
        if face == 3:
            running = sw.running()
            b1 = [300, BTN_Y, 500, BTN_Y + 60]
            b2 = [524, BTN_Y, 724, BTN_Y + 60]
            btn(scr, b1, "停止" if running else "开始",
                fill=C_RED if running else C_GREEN, size=24, cn=True, radius=14)
            btn(scr, b2, "复位", fill=C_GREY_BT, size=24, cn=True, radius=14)

        scr.flush()

        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            # 切表盘
            bx = 36
            for i, nm in enumerate(FACES):
                w = scr.tw(nm, 17, cn=True) + 30
                if hit([bx, 62, bx + w, 96], x, y):
                    face = i
                    if i != 3:
                        sw.reset()
                    break
                bx += w + 8
            # 秒表按钮
            if face == 3:
                if hit([300, BTN_Y, 500, BTN_Y + 60], x, y):
                    sw.stop() if sw.running() else sw.start()
                elif hit([524, BTN_Y, 724, BTN_Y + 60], x, y):
                    sw.reset()
