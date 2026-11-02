#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_gpuperf.py —— FPGA GPU 卸载效果对比实验

要回答的问题: **GPU 到底有没有用?**

残酷的前提(实测):
    填满整屏 1024x600   FPGA GPU 20.19 ms    CPU 只要 3.58 ms
    -> 单看填充速度, CPU 快 5.6 倍。GPU 唯一的价值是【不占 CPU】。

所以这个应用把 CPU 占住(真做 DFT 算频谱), 然后对比两种画法:
    GPU 版: GPU 异步画背景(20ms 的活, 提交完立刻返回) -> CPU 同时算频谱
            -> 收 GPU -> 再画网格和柱子
    CPU 版: CPU 自己填背景 -> 再算频谱 -> 再画网格和柱子

看的就是: **同样的计算负载下, 哪种画法帧率更高。**

界面:
    顶部   返回 / 标题 / 当前模式 / FPS
    中间   频谱可视化(网格 + 32 根柱子), 两种模式画的内容完全一样
    底部   负载 [-] [+] / 模式切换 / 各项耗时
"""
import ctypes
import math
import os
import time

from PIL import Image, ImageDraw

from fbui import font
from gpufill import GpuFill

W, H = 1024, 600
BAR_H = 56                      # 顶栏
BOT_H = 80                      # 底栏
CHART = (24, BAR_H + 12, W - 24, H - BOT_H - 12)
NBARS = 32                      # 柱子数

LOADS = [32, 64, 128, 192, 256]  # DFT 点数 = 负载档位


def make_signal(n):
    """合成一个"信号": 几个正弦叠加 + 一点噪声"""
    return [math.sin(i * 0.31) * 0.6 + math.sin(i * 0.07 + 1.2) * 0.3
            + math.sin(i * 1.7) * 0.1 for i in range(n)]


_TW = {}


def twiddle(n):
    """预计算旋转因子, 免得 DFT 内层反复调 sin/cos"""
    t = _TW.get(n)
    if t is None:
        t = [(math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n))
             for k in range(n)]
        _TW[n] = t
    return t


def spectrum(sig, n):
    """n 点 DFT, 只取前一半。这是真实的计算负载, 不是空转。"""
    tw = twiddle(n)
    half = n // 2
    out = []
    for k in range(half):
        re = im = 0.0
        for i in range(n):
            c, s = tw[(k * i) % n]
            v = sig[i]
            re += v * c
            im -= v * s
        out.append(math.hypot(re, im))
    m = max(out) or 1.0
    return [v / m for v in out]


class Perf:
    def __init__(self, scr, touch):
        self.scr = scr
        self.touch = touch
        self.sig = make_signal(256)
        self.load = 1                 # LOADS 下标
        self.mode = 0                 # 0 = GPU 画, 1 = CPU 画
        self.gf = GpuFill(scr)
        self.hw = self.gf.hw
        self.fps = 0.0
        self.t_calc = 0.0
        self.t_draw = 0.0
        self.t_gpu = 0.0
        self.gpu_px = 0
        self.frame = 0
        self.bars = [0.0] * NBARS
        # 背景 / 网格 / 柱子的矩形 (闭区间)
        x0, y0, x1, y1 = CHART
        self.bg = (0, 0, W - 1, H - 1)
        self.grid = []
        for i in range(NBARS + 1):
            gx = x0 + (x1 - x0) * i // NBARS
            self.grid.append((gx, y0, gx + 1, y1))
        for j in range(5):
            gy = y0 + (y1 - y0) * j // 4
            self.grid.append((x0, gy, x1, gy + 1))
        self.text_im = None
        self.text_raw = None
        self.last_txt = None

    # ---------- 按钮 ----------
    BTN_BACK = (10, 10, 130, 46)
    BTN_DN = (24, H - BOT_H + 14, 104, H - 20)
    BTN_UP = (114, H - BOT_H + 14, 194, H - 20)
    BTN_MODE = (210, H - BOT_H + 14, 420, H - 20)
    BTN_RST = (436, H - BOT_H + 14, 566, H - 20)

    def hit(self, r, x, y):
        return r[0] <= x <= r[2] and r[1] <= y <= r[3]

    # ---------- 一帧 ----------
    def step(self):
        t0 = time.time()
        sig = self.sig
        sp = spectrum(sig, LOADS[self.load])
        # 重采样到 NBARS 根柱子
        bars = []
        for i in range(NBARS):
            a = len(sp) * i // NBARS
            b = max(a + 1, len(sp) * (i + 1) // NBARS)
            bars.append(max(sp[a:b]))
        self.bars = bars
        self.t_calc = (time.time() - t0) * 1000.0

    def draw_gpu(self):
        """GPU 版: 背景异步提交(和 CPU 计算重叠), 网格和柱子再补"""
        gf = self.gf
        gf.begin()
        gf.post(*self.bg, 0x0A0E18)          # 整屏背景, 提交完立刻返回
        return gf

    def draw_cpu(self):
        """CPU 版: 用 C 写的 CPU 填充器填背景 (和 GPU 版同一份矩形表)"""
        gf = self.gf
        gf.begin()
        gf.rect(*self.bg, 0x0A0E18)
        gf.commit_cpu()

    def finish_draw(self, gpu_mode):
        """画网格 + 柱子 —— 两种模式用【同一份矩形表】, 只是出口不同"""
        if gpu_mode:
            gf = self.gf
            gf.begin()
            for (a, b, c, d) in self.grid:
                gf.rect(a, b, c, d, 0x1E2C44)
            for i, v in enumerate(self.bars):
                bx = CHART[0] + (CHART[2] - CHART[0]) * i // NBARS + 2
                bw = (CHART[2] - CHART[0]) // NBARS - 3
                bh = int((CHART[3] - CHART[1]) * v)
                gf.rect(bx, CHART[3] - bh, bx + bw, CHART[3], 0x38D070)
            gf.commit()
        else:
            gf = self.gf
            gf.begin()
            for (a, b, c, d) in self.grid:
                gf.rect(a, b, c, d, 0x1E2C44)
            for i, v in enumerate(self.bars):
                bx = CHART[0] + (CHART[2] - CHART[0]) * i // NBARS + 2
                bw = (CHART[2] - CHART[0]) // NBARS - 3
                bh = int((CHART[3] - CHART[1]) * v)
                gf.rect(bx, CHART[3] - bh, bx + bw, CHART[3], 0x38D070)
            gf.commit_cpu()

    def hud(self, extra):
        """HUD 文字 (只在内容变了才重画)"""
        txt = extra
        if txt != self.last_txt:
            im = Image.new("RGB", (W, BOT_H - 24), (13, 13, 13))
            d = ImageDraw.Draw(im)
            d.text((180, 6), txt, font=font(17, bold=True),
                   fill=(200, 224, 255))
            d.text((180, 30), "GPU 卸载: 背景填充提交后立刻返回, CPU 拿这段时间"
                              "去算频谱", font=font(15, cn=True),
                   fill=(120, 150, 190))
            self.text_raw = self.scr.to_raw(im)
            self.last_txt = txt
        self.scr.blit_raw(0, H - BOT_H + 8, W, BOT_H - 24, self.text_raw)

    def run(self):
        scr = self.scr
        touch = self.touch
        press = None
        t_fps = time.time()
        prev = None
        # 静态: 顶栏/底栏 + 三个按钮 (一次画好)
        bar = Image.new("RGB", (W, BAR_H), (10, 10, 10))
        d = ImageDraw.Draw(bar)
        d.rectangle(list(self.BTN_BACK), fill=(46, 66, 104),
                    outline=(150, 180, 220))
        d.polygon([(26, 28), (40, 16), (40, 40)], fill=(243, 243, 243))
        d.text((50, 16), "返回", font=font(20, bold=True, cn=True),
               fill=(243, 243, 243))
        d.text((150, 16), "FPGA GPU 卸载效果对比", font=font(20, cn=True),
               fill=(200, 220, 245))
        bar_raw = scr.to_raw(bar)
        bot = Image.new("RGB", (W, BOT_H), (10, 10, 10))
        db = ImageDraw.Draw(bot)
        fbtn = font(17, bold=True, cn=True)
        for r, lbl, col in ((self.BTN_DN, "负载 -", (70, 110, 170)),
                            (self.BTN_UP, "负载 +", (70, 110, 170)),
                            (self.BTN_RST, "清零统计", (92, 92, 92))):
            x0, x1 = r[0], r[2]
            y0, y1 = r[1] - (H - BOT_H), r[3] - (H - BOT_H)
            rr_(db, [x0, y0, x1, y1], 10, fill=col, outline=(238, 238, 238))
            try:
                tw = db.textlength(lbl, font=fbtn)
            except AttributeError:
                tw = db.textsize(lbl, font=fbtn)[0]
            db.text(((x0 + x1 - tw) / 2, (y0 + y1) // 2 - 11), lbl,
                    font=fbtn, fill=(255, 255, 255))
        bot_raw = scr.to_raw(bot)

        # GPU/CPU 模式的按钮文字是变的, 单独一块
        mode_im = Image.new("RGB", (210, 52), (35, 35, 35))
        mode_raw = None

        n = 0
        t_stat = time.time()
        s_calc = s_draw = s_gpu = 0.0
        while True:
            t0 = time.time()
            # ---- 输入 ----
            while True:
                ev = touch.poll(move=True)
                if ev is None:
                    break
                kind, tx, ty = ev
                if kind in ("down", "tap"):
                    press = (tx, ty)
                elif kind == "up":
                    press = None
            if press is None and getattr(touch, "down", False):
                press = (touch.x, touch.y)
            if press:
                if self.hit(self.BTN_BACK, *press):
                    return
                if self.hit(self.BTN_DN, *press):
                    self.load = max(0, self.load - 1)
                elif self.hit(self.BTN_UP, *press):
                    self.load = min(len(LOADS) - 1, self.load + 1)
                elif self.hit(self.BTN_MODE, *press):
                    self.mode = 1 - self.mode
                elif self.hit(self.BTN_RST, *press):
                    s_calc = s_draw = s_gpu = 0.0
                    n = 0
                    t_stat = time.time()

            gpu_mode = (self.mode == 0 and self.hw)

            # ---- 绘制 (顺序就是实验的核心) ----
            t_a = time.time()
            if gpu_mode:
                self.draw_gpu()             # ① 提交 20ms 的整屏背景, 不等待
            else:
                self.draw_cpu()             # ① CPU 自己填
            t_b = time.time()
            self.step()                     # ② 算频谱 (GPU 版在这段时间和 GPU 并行)
            t_c = time.time()
            if gpu_mode:
                self.gf.sync()              # ③ 收 GPU
            self.finish_draw(gpu_mode)      # ④ 网格 + 柱子
            t_d = time.time()

            self.t_draw = (t_b - t_a) * 1000.0
            self.t_gpu = (t_c - t_b) * 1000.0      # 计算期间 GPU 在跑
            self.t_calc = (t_c - t_b) * 1000.0

            # ---- HUD (全部走 blit_raw 直接写显存; 绝不整屏 flush,
            #      整屏 flush 一次要 35ms, 会把整个实验淹掉) ----
            d2 = ImageDraw.Draw(mode_im)
            d2.rectangle([0, 0, 209, 51], fill=(35, 35, 35),
                         outline=(238, 238, 238))
            d2.text((16, 13), "模式: " + ("FPGA GPU" if gpu_mode else "纯 CPU"),
                    font=font(19, bold=True, cn=True), fill=(255, 240, 180))
            mode_raw = scr.to_raw(mode_im)
            scr.blit_raw(0, 0, W, BAR_H, bar_raw)
            scr.blit_raw(0, H - BOT_H, W, BOT_H, bot_raw)
            scr.blit_raw(self.BTN_MODE[0], self.BTN_MODE[1], 210, 52, mode_raw)
            self.hud("负载 %d 点DFT   FPS %4.1f   画 %.1fms  算 %.1fms"
                     % (LOADS[self.load], self.fps, self.t_draw, self.t_calc))

            n += 1
            s_calc += self.t_calc
            s_draw += self.t_draw
            now = time.time()
            if n % 10 == 0:
                el = now - t_stat
                self.fps = n / max(1e-6, el)
                try:
                    with open("/tmp/gpuperf.txt", "w") as fh:
                        fh.write("mode=%s  load=%d  FPS=%.1f  "
                                 "画图=%.2fms  计算=%.2fms  帧=%.2fms\n"
                                 % ("GPU" if gpu_mode else "CPU",
                                    LOADS[self.load], self.fps,
                                    s_draw / n, s_calc / n, el * 1000.0 / n))
                except Exception:
                    pass
                n = 0
                s_calc = s_draw = 0.0
                t_stat = now


def rr_(d, xy, r, fill=None, outline=None):
    """圆角矩形 (PIL 7 没有 rounded_rectangle)"""
    x0, y0, x1, y1 = xy
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    if fill:
        d.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        d.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        for cx, cy in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r),
                       (x1 - 2 * r, y1 - 2 * r)):
            d.ellipse([cx, cy, cx + 2 * r, cy + 2 * r], fill=fill)
    if outline:
        d.rectangle([x0, y0, x1, y1], outline=outline)


def run(scr, touch):
    Perf(scr, touch).run()
