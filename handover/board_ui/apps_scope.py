#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_scope.py —— 数字示波器 (板载桌面应用)

PL 里是一个 4096 点双 bank 采集器 (触发/预触发/抽取/内部 DDS 信号源),
PS 这边只负责: 读一帧 -> 量一下 -> 画出来。

两个信号源:
    DDS    —— PL 内部 DDS 产生的已知波形 (正弦/方波/三角/锯齿), 自检用
    ADC    —— 外部 8 位并行 ADC (接摄像头 DVP 口; 还没接线时是 0)
"""
import time

from fbui import header, back_hit, btn, hit
from scope import (Scope, WAVE_NAMES, MODE_NAMES, WAVE_SINE, WAVE_SQUARE,
                   WAVE_TRI, WAVE_SAW, MODE_AUTO, MODE_NORMAL, MODE_SINGLE,
                   TIMEBASES, FCLK_HZ)

# ---------------- 布局 ----------------
W, H = 1024, 600
STAT_Y = 62
STAT_BOX = [0, STAT_Y + 20, W, STAT_Y + 46]   # 只重画数值这一条带
WAVE = [8, 112, 1016, 468]
GRID_C, GRID_R = 10, 8

BTN_Y1 = 478
BTN_Y2 = 532
BTN_H = 42

C_BG = (11, 11, 11)
C_GRID = (36, 36, 36)
C_GRID_MAJ = (44, 64, 96)
C_TRACE = (90, 255, 170)
C_TRIG = (255, 176, 64)
C_TXT = (198, 220, 245)
C_DIM = (110, 140, 180)


class ScopeApp:
    def __init__(self, scr):
        self.scr = scr
        self.sc = Scope()
        self.run = True
        self.wave = WAVE_SINE
        self.mode = MODE_AUTO
        self.tb = 4                     # 1us/点
        self.triglev = 128
        self.src_dds = True
        self.data = bytearray(4096)
        self.meas = {}
        self.n = 0
        self.t0 = time.time()
        self.fps = 0.0
        self.bg = None
        self.msg = ""
        self.apply()

    # ---------------- 配置下发 ----------------
    def apply(self):
        self.sc.configure(src=0 if self.src_dds else 1,
                          wave=self.wave,
                          timebase=self.tb,
                          triglev=self.triglev,
                          edge=0,
                          mode=self.mode,
                          pre=2048)
        # DDS 频率: 让默认窗口 (~4096 点) 里大约 20 个周期
        div, dec, _ = TIMEBASES[self.tb]
        # 显示窗宽 = 4096 * div*dec/100MHz
        span = 4096.0 * div * dec / FCLK_HZ
        want = 20.0 / max(span, 1e-9)
        # DDS 必须低于基础采样率的奈奎斯特
        want = min(want, 8.0e6)
        self.sc.configure(dds_hz=want)
        self.dds_hz = want

    # ---------------- 采集 ----------------
    def step(self):
        if self.run:
            if self.sc.capture():
                self.data = self.sc.read_frame(4096)
                self.meas = self.sc.measure(self.data)
            self.n += 1
            el = time.time() - self.t0
            if el >= 0.5:
                self.fps = self.n / el
                self.n = 0
                self.t0 = time.time()

    # ---------------- 静态背景 ----------------
    def make_bg(self):
        """画一次网格和按钮, 存成图; 每帧只重画波形区"""
        scr = self.scr
        scr.clear(C_BG)
        header(scr, "数字示波器  (PL 4096 点双 bank 采集)")

        # ---- 状态栏: 底色 + 7 个静态标签 (数值每帧另画) ----
        scr.rect([0, STAT_Y, W, WAVE[1] - 4], fill=(19, 19, 19))
        self.stat_x = [14 + i * 146 for i in range(7)]
        for i, lbl in enumerate(("频率", "Vpp", "电平", "占空",
                                 "时基", "触发", "FPS")):
            scr.text((self.stat_x[i], STAT_Y + 4), lbl, 13, C_DIM, cn=True)

        x0, y0, x1, y1 = WAVE
        scr.rect([x0, y0, x1, y1], fill=(7, 7, 7))
        for i in range(GRID_C + 1):
            x = x0 + (x1 - x0) * i // GRID_C
            maj = (i == 0 or i == GRID_C or i == GRID_C // 2)
            scr.d.line([(x, y0), (x, y1)],
                       fill=C_GRID_MAJ if maj else C_GRID, width=1)
        for j in range(GRID_R + 1):
            y = y0 + (y1 - y0) * j // GRID_R
            maj = (j == 0 or j == GRID_R or j == GRID_R // 2)
            scr.d.line([(x0, y), (x1, y)],
                       fill=C_GRID_MAJ if maj else C_GRID, width=1)
        scr.rrect([x0 - 1, y0 - 1, x1 + 1, y1 + 1], 4,
                  fill=None, outline=(60, 86, 126), width=2)

        # 按钮
        self.btns = {}
        labels1 = [("wave", "波形"), ("tb-", "时基 -"),
                   ("tb+", "时基 +"), ("mode", "触发模式")]
        labels2 = [("lv-", "电平 -"), ("lv+", "电平 +"),
                   ("run", "停止"), ("auto", "自动设置")]
        bw = (W - 16 - 3 * 8) // 4
        for row, labels in ((BTN_Y1, labels1), (BTN_Y2, labels2)):
            for i, (key, lbl) in enumerate(labels):
                r = [8 + i * (bw + 8), row, 8 + i * (bw + 8) + bw, row + BTN_H]
                btn(scr, r, lbl, fill=(46, 66, 104), size=19, cn=True)
                self.btns[key] = r
        # 源切换按钮放右上角
        r = [W - 190, 8, W - 10, 52]
        btn(scr, r, "源: DDS", fill=(60, 96, 60), size=19, cn=True)
        self.btns["src"] = r

        scr.text((W // 2, H - 10),
                 "网格 10x8   触摸下面的按钮操作   DDS 是 PL 内部信号源 (自检用)",
                 14, C_DIM, cn=True, anchor="mm")
        self.bg = scr.img.copy()

        # 波形区的"底图"(网格)原始字节 + 可复用缓冲。
        # 每帧 buf[:] = bg_raw (一次 memcpy) 再往上画触发电平/波形, 最后
        # blit_raw 直写显存 —— 完全不碰 PIL。这一段从 90ms 降到 ~2ms。
        x0, y0, x1, y1 = WAVE
        self.ww = x1 - x0
        self.wh = y1 - y0
        raw = scr.img.crop((x0, y0, x0 + self.ww, y0 + self.wh))
        self.bg_raw = bytearray(scr.to_raw(raw))
        self.wave_buf = bytearray(len(self.bg_raw))

    # ---------------- 状态栏 ----------------
    def draw_stat(self):
        """只重画"数值"那一条带, 标签是静态的 (跟底图一起预渲染)。

        原来每帧重画 14 个中文文本 (7 标签 + 7 数值) 要 ~18ms;
        现在每帧只画 7 个数值 + 一次 to_raw/blit (1024x26)。
        """
        scr = self.scr
        m = self.meas
        freq = m.get("freq")
        if not freq:
            f_txt = "  -- kHz"
        elif freq >= 1e6:
            f_txt = "%7.3f MHz" % (freq / 1e6)
        else:
            f_txt = "%7.2f kHz" % (freq / 1000.0)

        items = [
            (f_txt, (120, 240, 180)),
            ("%3d LSB" % m.get("pp", 0), (255, 214, 140)),
            ("%3d" % self.triglev, (255, 176, 64)),
            ("%4.1f%%" % m.get("duty", 0.0), (180, 210, 240)),
            (TIMEBASES[self.tb][2], (200, 180, 255)),
            (MODE_NAMES[self.mode], (255, 186, 120)),
            ("%4.1f" % self.fps, (150, 190, 230)),
        ]

        bx0, by0, bx1, by1 = STAT_BOX
        scr.img.paste(self.bg.crop(STAT_BOX), (bx0, by0))
        for i, (val, col) in enumerate(items):
            scr.text((self.stat_x[i], by0 + 2), val, 17, col,
                     cn=True, bold=True)
        raw = scr.to_raw(scr.img.crop(STAT_BOX))
        scr.blit_raw(bx0, by0, bx1 - bx0, by1 - by0, raw)

    # ---------------- 波形 ----------------
    def draw_wave(self):
        """整块波形区走裸字节 + C 渲染 + blit_raw, 不碰 PIL。

        实测: PIL 画 1024 条竖线要 90ms/帧 (整机只有 8 FPS),
              换成 C 渲染 + blit_raw 后约 2ms。
        """
        scr = self.scr
        x0, y0 = WAVE[0], WAVE[1]
        w, h = self.ww, self.wh
        buf = self.wave_buf
        buf[:] = self.bg_raw                     # 先把网格底图拷回来

        # ---- 触发电平虚线 (橙色) ----
        ty = max(1, min(h - 2, h - 1 - int(self.triglev * (h - 1) / 255.0)))
        tb, tg, tr = C_TRIG[2], C_TRIG[1], C_TRIG[0]
        for xx in range(2, w - 7, 12):
            for k in range(6):
                o = (ty * w + xx + k) * 3
                buf[o] = tb
                buf[o + 1] = tg
                buf[o + 2] = tr

        # ---- 触发位置竖线 (预触发 2048/4096, 在正中间) ----
        tx = w // 2
        for yy in range(2, h - 7, 12):
            for k in range(6):
                o = ((yy + k) * w + tx) * 3
                if o + 2 < len(buf):
                    buf[o] = 60
                    buf[o + 1] = 120
                    buf[o + 2] = 255

        # ---- 波形: C 里按每列 min/max 画竖线 ----
        # C_TRACE = (90, 255, 170) -> 0xRRGGBB = 0x5AFFAA
        self.sc.render(buf, w, h, self.data, 0x5AFFAA)

        scr.blit_raw(x0, y0, w, h, buf)

    # ---------------- 触摸 ----------------
    def handle(self, x, y):
        b = self.btns
        if back_hit(x, y):
            return False
        if hit(b["wave"], x, y):
            self.wave = (self.wave + 1) % 4
            self.sc.configure(wave=self.wave)
        elif hit(b["tb-"], x, y):
            self.tb = max(0, self.tb - 1)
            self.apply()
        elif hit(b["tb+"], x, y):
            self.tb = min(len(TIMEBASES) - 1, self.tb + 1)
            self.apply()
        elif hit(b["mode"], x, y):
            self.mode = (self.mode + 1) % 3
            self.sc.configure(mode=self.mode)
        elif hit(b["lv-"], x, y):
            self.triglev = max(0, self.triglev - 8)
            self.sc.configure(triglev=self.triglev)
        elif hit(b["lv+"], x, y):
            self.triglev = min(255, self.triglev + 8)
            self.sc.configure(triglev=self.triglev)
        elif hit(b["run"], x, y):
            self.run = not self.run
        elif hit(b["auto"], x, y):
            self.auto_set()
        elif hit(b["src"], x, y):
            self.src_dds = not self.src_dds
            self.apply()
        self.redraw_buttons()
        return True

    def auto_set(self):
        """自动设置: 按实测频率挑一个合适的时基, 让窗口里约 10 个周期"""
        m = self.meas
        f = m.get("freq")
        if f and f > 0:
            best, bestd = self.tb, 1e18
            for i, (div, dec, _) in enumerate(TIMEBASES):
                span = 4096.0 * div * dec / FCLK_HZ
                want = 10.0 / span
                d = abs(want - f) / f
                if d < bestd:
                    bestd, best = d, i
            self.tb = best
        self.mode = MODE_AUTO
        self.triglev = 128
        self.run = True
        self.apply()
        self.msg = "自动设置完成"

    def redraw_buttons(self):
        scr = self.scr
        # 只需要更新文字会变的两个: run / src
        r = self.btns["run"]
        scr.img.paste(self.bg.crop((r[0], r[1], r[2] + 1, r[3] + 1)),
                      (r[0], r[1]))
        btn(scr, r, "运行" if not self.run else "停止",
            fill=(40, 110, 70) if not self.run else (46, 66, 104),
            size=19, cn=True)
        scr.flush(box=(r[0], r[1], r[2] + 1, r[3] + 1))

        r = self.btns["src"]
        scr.img.paste(self.bg.crop((r[0], r[1], r[2] + 1, r[3] + 1)),
                      (r[0], r[1]))
        btn(scr, r, "源: DDS" if self.src_dds else "源: ADC",
            fill=(60, 96, 60) if self.src_dds else (110, 70, 60),
            size=19, cn=True)
        scr.flush(box=(r[0], r[1], r[2] + 1, r[3] + 1))


def run(scr, touch):
    app = ScopeApp(scr)
    app.make_bg()
    scr.flush()
    app.draw_stat()
    app.draw_wave()
    last = time.time()
    while True:
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if not app.handle(x, y):
                return
        app.step()
        app.draw_wave()
        app.draw_stat()
        # 采一帧本身就要时间(慢时基下几十毫秒), 所以只在很快的时候补一点睡
        dt = time.time() - last
        if dt < 0.01:
            time.sleep(0.01 - dt)
        last = time.time()
