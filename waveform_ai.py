#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""waveform_ai.py —— 波形 → 时频图 → CNN 的完整链路（A7 的软件部分）

════════════════════════════════════════════════════════════════════
这条链在整个项目里的位置
════════════════════════════════════════════════════════════════════
项目最初的思路是：
    一维电压波形 → 转换成二维图像 → 送轻量 CNN → 自动识别波形类型 / 检测故障

"转换成二维图像"这一步，最经典也最有效的做法就是 **STFT（短时傅里叶变换）**：
把一维时域信号切成很多小段，每段做 FFT，把幅度谱按时间排开 —— 得到一张
"时间 × 频率"的二维图（时频图 / 语谱图）。

    ┌──────────────────────────┐
    │  示波器 4096 点 @ 20MSPS  │   ← 已有的自研示波器 PL
    └───────────┬──────────────┘
                │
        ┌───────▼────────┐
        │   STFT         │   ← 本文件
        │ 窗 256 重叠128  │
        └───────┬────────┘
                │ 时频图（幅度谱矩阵）
        ┌───────▼────────┐
        │ 缩放到 28×28    │   ← 复用上一轮 MNIST 的 CNN 输入尺寸
        │ 量化成 int8     │     （这样不用改网络结构）
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │  CNN 加速器     │   ← 已集成进 PL（0x43CD0000 / 0x43CE0000）
        │ cnn_conv_pool_q │
        │ cnn_fc_q        │
        └───────┬────────┘
                │
            波形类别 / 异常标志

════════════════════════════════════════════════════════════════════
★ 两条硬约束（决定了实现方式）
════════════════════════════════════════════════════════════════════
1. **不能用 numpy**
   任务分解里写着"numpy 版本需确认；若没有，用 audioop 或自写 FFT"。
   为了不赌，这里**全部纯 Python**（只用标准库 array/math）。
   ⇒ 自己写 radix-2 FFT。

2. **内存要省**
   之前用 Python list 处理 55MB 音频把板子内存吃爆（653MB / 总共 1GB），
   所以这里一律用 `array` 模块，并且**流式处理**、不整段驻留。

════════════════════════════════════════════════════════════════════
波形类别（10 类，和 CNN 的 10 个输出对齐）
════════════════════════════════════════════════════════════════════
    0  正弦波        sine
    1  方波          square
    2  三角波        triangle
    3  锯齿波        sawtooth
    4  脉冲串        pulse
    5  调幅波        am
    6  调频波        fm
    7  白噪声        noise
    8  直流/静默     flat
    9  工频干扰      hum（50Hz + 谐波，现实中很常见）

★ 类别是自己定的 —— 如果 AI 负责人要换，改 `CLASSES` 就行，
  但那时**CNN 的 FC 输出维度也要跟着改**（现在是 10）。

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    python waveform_ai.py --selftest              # ★ 离线自测整条链（不需要板子）
    python waveform_ai.py --demo                  # 看各类波形的特征图摘要
    python waveform_ai.py --gen-dataset 200       # 生成训练数据集（给 AI 负责人）
    python waveform_ai.py --classify 波形.bin     # 用 CNN 推理一个波形文件
"""
import argparse
import array
import json
import math
import os
import random
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 常量
FS_DEFAULT = 20_000_000        # ★ 示波器基础采样率 20 MSPS（100MHz / DIV=5）
SCOPE_POINTS = 4096            # ★ 示波器采集深度

CNN_SIZE = 28                  # ★ 和 PL 上 CNN 加速器的输入尺寸一致

STFT_WIN = 256                 # 窗长
STFT_HOP = 128                 # 步长（50% 重叠）
STFT_WINDOW = "hann"           # 窗函数
EPS = 1e-9

# ★★★ 输入表示：wdens（时间×幅度密度图），不是 STFT ★★★
#
# 这是 AI 训练负责人交付包 v1.0 的结论，我照做。理由（实测，见
# `02_文档/01_输入表示选型.md`）：
#
#   STFT 要分开谐波，需要「一个窗内至少 2 个周期」：
#       窗口内周期数 = K × NFFT / 4096
#   但示波器为了"屏幕上看 2~5 个周期"，缓冲区内只有 K = 2~5 个周期
#   ⇒ 窗内只有 0.25~0.6 个周期 ⇒ 【谐波完全糊在一起】，分不开。
#
#   密度图在少周期时直接呈现波形形状；多周期时每个时间列内退化为
#   【幅度分布】，而正弦(反正弦分布)/三角(均匀)/方波(双尖峰)/噪声(高斯)
#   的幅度分布本来就各不相同 —— 两个工况下都有判别力。
#
# ⇒ 默认用 wdens。STFT 代码保留（`mode="stft"`），但不再作为默认。
PP_MODE = "wdens"
NCOLS_D = 28                   # 时间列
NROWS_D = 28                   # 幅度行（行 0 = 顶部 = 高电平）

# ★ 8 个波形类别 —— 和交付包 model_spec.json 的 classes 逐字一致，顺序也一样
#   （下标即 CNN 输出下标，顺序错了就全错）
CLASSES = [
    ("sine",           "正弦波"),
    ("square",         "方波"),
    ("triangle",       "三角波"),
    ("sawtooth",       "锯齿波"),
    ("noise",          "噪声/无周期信号"),
    ("clipping",       "削顶（含轻度削顶）"),
    ("signal_loss",    "丢信号（平线或强衰减）"),
    ("duty_abnormal",  "占空比异常"),
]
CLASS_NAMES = [c[0] for c in CLASSES]

# ★★ 为什么没有毛刺（glitch）类：
#   毛刺只有 2~10 个采样点，映射到 28×28 密度图后只改变 2~5/784 个像素，
#   在这个表示上做分类只能收敛到多数类（实测召回 0.000）——
#   **在 4096 点采集 + 28×28 画布上不可分**。
#   按 06_分工总表 的分工，毛刺归【示波器负责人的 PL 硬件故障检测器】
#   （100 MHz / 10 ns 分辨率）。这里不重复做。
GLITCH_NOTE = ("毛刺由 PL 硬件检测器负责（10ns 分辨率），"
               "在 28×28 画布上不可分，本模型 8 类不含它")


# ══════════════════════════════════════════════════════════════════
#  ① 波形生成（可复现 —— 同一个 seed 出同一段波形）
# ══════════════════════════════════════════════════════════════════
def gen_wave(kind, n=SCOPE_POINTS, fs=FS_DEFAULT, freq=10000.0,
             amp=1.0, noise=0.02, seed=1, duty=0.3, fm_dev=0.2, am_depth=0.6,
             clip_v=0.4, loss_db=40.0):
    """生成一段波形，返回 array('f')（浮点，范围大约 ±amp）

    ★ kind 必须是 CLASSES 里的 8 类之一：
        sine / square / triangle / sawtooth / noise
        clipping（削顶，clip_v 越小削得越狠）
        signal_loss（丢信号，loss_db 越大越接近平线）
        duty_abnormal（占空比异常，duty 偏离 0.5）

      老的 am / fm / pulse / flat / hum 保留着（数据集可能还在用），
      但它们不在交付模型的 8 类里。

    ★ 全部可复现：给同一个 seed 一定出同一段数据，方便做数据集和回归测试。
    """
    rnd = random.Random(seed)
    out = array.array("f")
    ap = out.append
    w = 2.0 * math.pi * freq / fs

    for i in range(n):
        t = i
        if kind == "sine":
            v = amp * math.sin(w * t)
        elif kind == "square":
            v = amp if math.sin(w * t) >= 0 else -amp
        elif kind == "triangle":
            # 归一到 [-1,1]
            ph = (freq * t / fs) % 1.0
            v = amp * (4.0 * abs(ph - 0.5) - 1.0) * -1.0
        elif kind == "sawtooth":
            ph = (freq * t / fs) % 1.0
            v = amp * (2.0 * ph - 1.0)
        elif kind == "pulse":
            ph = (freq * t / fs) % 1.0
            v = amp if ph < duty else -amp * 0.1
        elif kind == "clipping":
            # ★ 削顶：正弦被硬限幅（含轻度削顶）
            #   clip_v 越小削得越狠（0.4 = 削掉约 40%）
            s = math.sin(w * t)
            lim = clip_v
            v = amp * (lim if s > lim else (-lim if s < -lim else s)) / lim
        elif kind == "signal_loss":
            # ★ 丢信号：平线 或 强衰减后的残余
            #   loss_db 越大越接近纯平线
            g = 10.0 ** (-loss_db / 20.0)
            v = amp * g * math.sin(w * t)
        elif kind == "duty_abnormal":
            # ★ 占空比异常：方波但占空比偏离 50%
            ph = (freq * t / fs) % 1.0
            v = amp if ph < duty else -amp
        elif kind == "am":
            v = amp * (1.0 + am_depth * math.sin(2 * math.pi * freq * 0.1
                                                  * t / fs)) * math.sin(w * t) / \
                (1.0 + am_depth)
        elif kind == "fm":
            # 瞬时相位积分：phi += 2π(f + dev·sin(2π fm t))/fs
            # 用解析式近似（dev 小的时候够用），避免逐点累加漂移
            beta = fm_dev * amp
            v = amp * math.sin(w * t + beta * math.sin(2 * math.pi * freq * 0.05
                                                       * t / fs))
        elif kind == "noise":
            v = amp * rnd.uniform(-1, 1)
        elif kind == "flat":
            v = amp * 0.02
        elif kind == "hum":
            # 50Hz 工频 + 3/5 次谐波（现实中最常见的干扰）
            v = amp * (0.6 * math.sin(2 * math.pi * 50 * t / fs)
                       + 0.3 * math.sin(2 * math.pi * 150 * t / fs)
                       + 0.15 * math.sin(2 * math.pi * 250 * t / fs))
        else:
            raise ValueError("未知波形类型: %s" % kind)

        if noise:
            v += rnd.gauss(0, noise * amp)
        # 夹到 8bit 示波器范围对应的大致区间
        if v > 1.0:
            v = 1.0
        elif v < -1.0:
            v = -1.0
        ap(v)
    return out


def quantize_8bit(samples):
    """浮点波形 -> 8bit 无符号（模拟示波器实际采到的数据）"""
    out = array.array("B")
    for v in samples:
        q = int(round((v + 1.0) * 127.5))
        if q < 0:
            q = 0
        elif q > 255:
            q = 255
        out.append(q)
    return out


# ══════════════════════════════════════════════════════════════════
#  ② FFT（纯 Python radix-2，迭代版）
# ══════════════════════════════════════════════════════════════════
def _bit_reverse(a):
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]


def fft(re, im):
    """原地 radix-2 FFT。长度必须是 2 的幂。

    ★ 为什么自己写：板上 numpy 版本不确定，而这个算法只有 30 行，
      256 点的 FFT 在 A9 上也就几十微秒，够用。
    """
    n = len(re)
    if n & (n - 1):
        raise ValueError("FFT 长度必须是 2 的幂，收到 %d" % n)
    _bit_reverse(re)
    _bit_reverse(im)

    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wr = math.cos(ang)
        wi = math.sin(ang)
        half = length >> 1
        for i in range(0, n, length):
            cr, ci = 1.0, 0.0
            for k in range(i, i + half):
                ur, ui = re[k], im[k]
                vr = re[k + half] * cr - im[k + half] * ci
                vi = re[k + half] * ci + im[k + half] * cr
                re[k], im[k] = ur + vr, ui + vi
                re[k + half], im[k + half] = ur - vr, ui - vi
                # 递推旋转因子
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1


def _make_window(n, kind=STFT_WINDOW):
    if kind == "hann":
        return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)) for i in range(n)]
    if kind == "hamming":
        return [0.54 - 0.46 * math.cos(2.0 * math.pi * i / (n - 1)) for i in range(n)]
    return [1.0] * n


# ══════════════════════════════════════════════════════════════════
#  ③ STFT -> 幅度谱矩阵
# ══════════════════════════════════════════════════════════════════
def stft(samples, win=STFT_WIN, hop=STFT_HOP):
    """短时傅里叶变换，返回 [帧][频率bin] 的幅度（已做 sqrt 压缩）

    ★ 只用单边谱（0..win/2），因为实信号的负频率是冗余的。
    """
    w = _make_window(win)
    nbins = win // 2 + 1
    frames = []
    n = len(samples)
    pos = 0
    while pos + win <= n:
        re = [0.0] * win
        im = [0.0] * win
        for i in range(win):
            re[i] = samples[pos + i] * w[i]
        fft(re, im)
        mag = [0.0] * nbins
        for k in range(nbins):
            mag[k] = math.sqrt(re[k] * re[k] + im[k] * im[k])
        frames.append(mag)
        pos += hop
    return frames


# ══════════════════════════════════════════════════════════════════
#  ④ 时频图 -> 28x28 int8（CNN 能吃的形状）
# ══════════════════════════════════════════════════════════════════
def resize_bilinear(src, sw, sh, dw, dh):
    """双线性插值缩放（纯 Python）"""
    out = array.array("f", [0.0]) * (dw * dh)
    if sw < 2 or sh < 2 or dw < 1 or dh < 1:
        return out
    for y in range(dh):
        fy = (y + 0.5) * sh / dh - 0.5
        y0 = int(math.floor(fy))
        ty = fy - y0
        y0 = max(0, min(sh - 1, y0))
        y1 = max(0, min(sh - 1, y0 + 1))
        for x in range(dw):
            fx = (x + 0.5) * sw / dw - 0.5
            x0 = int(math.floor(fx))
            tx = fx - x0
            x0 = max(0, min(sw - 1, x0))
            x1 = max(0, min(sw - 1, x0 + 1))
            v00 = src[y0 * sw + x0]
            v01 = src[y0 * sw + x1]
            v10 = src[y1 * sw + x0]
            v11 = src[y1 * sw + x1]
            top = v00 * (1 - tx) + v01 * tx
            bot = v10 * (1 - tx) + v11 * tx
            out[y * dw + x] = top * (1 - ty) + bot * ty
    return out


def spectrum_to_image(frames, size=CNN_SIZE, log_compress=True):
    """把 STFT 的幅度谱矩阵变成 size×size 的 int8 图像（CNN 输入）

    ★ 三个处理步骤，每个都有理由：
      1. **对数压缩** —— 幅度谱动态范围极大（可能 5~6 个数量级），
         不压缩的话弱信号全被压成 0，特征全丢。
      2. **缩放到 28×28** —— 复用上一轮 MNIST CNN 的输入尺寸，
         这样网络结构不用改。
      3. **量化到 0..127** —— CNN 要 int8，而且训练时也必须是同一套量化，
         否则推理和训练对不上（这是最容易出错的地方）。
    """
    if not frames or not frames[0]:
        return array.array("B", [0] * (size * size))

    nf = len(frames)
    nb = len(frames[0])

    # 展平成 (帧 × bin) 的浮点矩阵
    flat_src = array.array("f")
    for fr in frames:
        flat_src.extend(fr)

    # ① 对数压缩
    if log_compress:
        flat = array.array("f")
        for v in flat_src:
            flat.append(math.log10(v + 1.0))
        flat_src = flat

    # ② 缩放
    small = resize_bilinear(flat_src, nb, nf, size, size)

    # ③ 量化到 0..127
    lo = min(small) if len(small) else 0.0
    hi = max(small) if len(small) else 1.0
    span = hi - lo
    out = array.array("B", [0] * (size * size))
    if span < EPS:
        return out
    for i, v in enumerate(small):
        q = int(round((v - lo) / span * 127.0))
        out[i] = 0 if q < 0 else (127 if q > 127 else q)
    return out


# ══════════════════════════════════════════════════════════════════
#  ③b 时间×幅度【密度图】(wdens) —— ★ 现在的默认输入表示
#
#  语义逐字照 AI 交付包的 `src/common/preprocess.py`：
#      · 28 列 = 时间：4096 点均分 28 段，每段 146 点（最后一列吃余数 154 点）
#      · 28 行 = 幅度：8 位码值 0..255 均分；行 0 = 顶部 = 高电平
#      · 每格 = 该列内落在该幅度档的【采样点个数】
#              → 除以该列点数得列内密度 → 开平方（方差稳定化）
#              → 按【本样本自身最大值】归一化到 0..255
#
#  ★ 为什么开平方：方差稳定化 —— 否则计数少的格子（弱轨迹）会被压没。
#  ★ 为什么按本样本归一化：不同幅度档的波形要能横向比。
# ══════════════════════════════════════════════════════════════════
def _col_bounds(n_samples, ncols=NCOLS_D):
    """28 列均分 n_samples 个采样点（最后一列吃掉余数）"""
    base = n_samples // ncols
    out = []
    for c in range(ncols):
        a = c * base
        b = n_samples if c == ncols - 1 else (c + 1) * base
        out.append((a, b))
    return out


def row_of_code(code, nrows=NROWS_D):
    """8 位码值 → 行号（0 = 顶部 = 高电平，nrows-1 = 底部 = 低电平）"""
    r = int((255 - code) * nrows / 256.0)
    if r < 0:
        r = 0
    if r > nrows - 1:
        r = nrows - 1
    return r


def wdens_u8(samples, size=CNN_SIZE):
    """4096 个 8 位样本 → 28×28 uint8 密度图（行=幅度，列=时间）

    samples: 可迭代的 0..255 整数（长度必须是 4096）
    返回 array('B')，长度 size*size
    """
    n = len(samples)
    if n != SCOPE_POINTS:
        raise ValueError("采集长度必须是 %d，实际 %d" % (SCOPE_POINTS, n))
    if size != NROWS_D or size != NCOLS_D:
        # 交付的模型锁定 28×28；换尺寸要么重训要么插值，这里只支持 28
        raise ValueError("wdens 锁定 %d×%d，收到 size=%d"
                         % (NROWS_D, NCOLS_D, size))

    # ① 每个采样点 → 行号
    rows = [row_of_code(int(v)) for v in samples]

    # ② 逐列统计直方图 → 密度 → sqrt
    #
    # ★★ 浮点运算顺序必须和交付包【逐字一致】★★
    #   我一开始写的是 sqrt(cnt * (1.0/n))，交付包是 sqrt(cnt / n) ——
    #   数学上一样，但浮点最后一位可能不同，再经过归一化和取整，
    #   就会出现 ±1 的码值偏差（实测 noise 波形上真的复现了）。
    #   这种偏差在板上会让逐点比对失败，而且极难查。
    #   ⇒ 所以这里严格照抄：先 cnt/n 再 sqrt；归一化也照抄 v/mx*255。
    img = [[0.0] * NCOLS_D for _ in range(NROWS_D)]
    for c, (a, b) in enumerate(_col_bounds(n)):
        cnt = [0] * NROWS_D
        for i in range(a, b):
            cnt[rows[i]] += 1
        npts = float(b - a)
        for r in range(NROWS_D):
            img[r][c] = math.sqrt(cnt[r] / npts)

    # ③ 按本样本最大值归一化到 0..255
    mx = 0.0
    for r in range(NROWS_D):
        for c in range(NCOLS_D):
            if img[r][c] > mx:
                mx = img[r][c]
    out = array.array("B", [0] * (size * size))
    if mx <= 0:
        return out
    for r in range(NROWS_D):
        base = r * NCOLS_D
        rowv = img[r]
        for c in range(NCOLS_D):
            q = int(math.floor(rowv[c] / mx * 255.0 + 0.5))
            out[base + c] = 0 if q < 0 else (255 if q > 255 else q)
    return out


def waveform_to_image(samples, size=CNN_SIZE, win=STFT_WIN, hop=STFT_HOP,
                      mode=None):
    """一步到位：波形 -> 28×28 图像（这是给 CNN 的东西）

    ★ mode:
        "wdens"（默认）—— 时间×幅度密度图，值域 0..255 uint8
        "stft"         —— 老的短时傅里叶谱，值域 0..127
                          （少周期工况下分不开谐波，仅作对照保留）

    ★★ 输入可以是两种，函数自己判断（这是个踩过的坑）：
        ① 浮点波形（范围约 ±1，gen_wave 的输出）→ 自动量化成 8bit
        ② 已经是 8bit 无符号（0..255，示波器采到的）→ 直接用

      为什么必须自动判断：wdens 是按【8 位 ADC 码值 0..255】分行做直方图的。
      如果直接把 ±1 的浮点丢进去，int(v) 只可能是 -1/0/1，
      全部落进第 0 行或第 27 行 —— **所有波形会变成同一张图**，
      而且不报错，只是分类全错。（实测就是这么踩的：自测里
      sine 和 square 的距离算出来是 0.00。）

    ★ 返回 array('B')，长度 size*size。
      送加速器时再做唯一变换：int8 = u8 - 128（见 to_int8_bytes）。
    """
    m = mode or PP_MODE

    # ---- 判断输入形态 ----
    vals = samples
    need_q = False
    try:
        head = list(samples)[:256]
    except TypeError:
        head = []
    if head:
        # 有任何负数 / 有浮点 → 当作浮点波形
        if min(head) < 0:
            need_q = True
        elif any(isinstance(v, float) for v in head):
            need_q = True
    if need_q:
        vals = quantize_8bit(list(samples))

    if m == "wdens":
        return wdens_u8(vals, size=size)
    frames = stft(vals, win, hop)
    return spectrum_to_image(frames, size)


def to_int8_bytes(img_u8):
    """★ 送 PL 加速器前的【唯一】变换：int8 = uint8 - 128

    为什么是 -128：8 位 ADC 码值的中心化（0..255 → -128..127），
    让网络的输入零均值。训练时用的是同一套，推理必须一致。
    """
    return bytes(((v - 128) & 0xFF) for v in img_u8)


# ══════════════════════════════════════════════════════════════════
#  ⑤ 数据集生成（给 AI 负责人训练用）
# ══════════════════════════════════════════════════════════════════
def make_dataset(per_class, out_dir, size=CNN_SIZE, seed0=1000):
    """生成训练/测试数据集

    输出三个文件：
        images.bin   每张 size*size 字节（int8，无符号 0..127）
        labels.bin   每张 1 字节（类别号）
        meta.json    说明（尺寸、类别、生成参数）

    ★ 关键：**训练用的量化方式必须和推理完全一致**（都在本文件里做），
      否则模型在 PC 上准、上板就废。所以数据集一定要用这个脚本生成。
    """
    os.makedirs(out_dir, exist_ok=True)
    img_path = os.path.join(out_dir, "images.bin")
    lbl_path = os.path.join(out_dir, "labels.bin")

    print("生成数据集：每类 %d 张，共 %d 张" % (per_class, per_class * len(CLASSES)))
    t0 = time.time()
    n = 0
    with open(img_path, "wb") as fi, open(lbl_path, "wb") as fl:
        for ci, (kind, cn) in enumerate(CLASSES):
            print("  [%d/%d] %-10s %s" % (ci + 1, len(CLASSES), kind, cn),
                  flush=True)
            for k in range(per_class):
                sd = seed0 + ci * 100000 + k
                rnd = random.Random(sd)
                # 随机化参数，让模型见到足够多的变化
                freq = rnd.uniform(2000, 200000)
                amp = rnd.uniform(0.4, 1.0)
                noise = rnd.uniform(0.005, 0.08)
                duty = rnd.uniform(0.15, 0.6)
                fm_dev = rnd.uniform(0.05, 0.5)
                am_depth = rnd.uniform(0.2, 0.9)
                pts = rnd.choice([2048, 4096])
                w = gen_wave(kind, n=pts, fs=FS_DEFAULT, freq=freq,
                             amp=amp, noise=noise, seed=sd, duty=duty,
                             fm_dev=fm_dev, am_depth=am_depth)
                img = waveform_to_image(w, size=size)
                fi.write(bytes(img))
                fl.write(bytes([ci]))
                n += 1

    meta = {
        "count": n,
        "per_class": per_class,
        "image_size": size,
        "image_bytes": size * size,
        "classes": [c[0] for c in CLASSES],
        "class_names_cn": [c[1] for c in CLASSES],
        "quant": "log10 compress -> bilinear resize -> normalize to 0..127 (uint8)",
        "fs": FS_DEFAULT,
        "stft_win": STFT_WIN,
        "stft_hop": STFT_HOP,
        "window": STFT_WINDOW,
        "note": "★ 训练必须用同一套预处理；推理时调 waveform_to_image() 即可",
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    # ★ 一定要显式 encoding="utf-8"：
    #   Windows 上 open(...,"w") 默认用 GBK(cp936)，Linux 上默认 UTF-8。
    #   不写的话，同一份代码在两个平台产出的 meta.json 编码不同，
    #   在另一台机器上读中文类别名就乱码。（这个坑已经踩过一次）

    dt = time.time() - t0
    print("\n 完成：%d 张，耗时 %.1f 秒（%.1f ms/张）" % (n, dt, dt * 1000 / max(1, n)))
    print("   %s" % img_path)
    print("   %s" % lbl_path)
    print("   %s" % os.path.join(out_dir, "meta.json"))
    return n


# ══════════════════════════════════════════════════════════════════
#  ⑥ 特征图摘要（人看的，用来判断"这张图有没有区分度"）
# ══════════════════════════════════════════════════════════════════
def image_summary(img, size=CNN_SIZE):
    """把 28×28 的图渲染成字符画 + 统计"""
    lines = []
    for y in range(size):
        row = []
        for x in range(size):
            v = img[y * size + x]
            row.append(" .:-=+*#%@"[min(9, v * 10 // 128)])
        lines.append("".join(row))
    vals = list(img)
    return {
        "art": "\n".join(lines),
        "min": min(vals), "max": max(vals),
        "mean": sum(vals) / len(vals),
        "nonzero": sum(1 for v in vals if v),
    }


# ══════════════════════════════════════════════════════════════════
#  ⑦ 和 CNN 对接
# ══════════════════════════════════════════════════════════════════
def classify_with_cnn(img, cnn_script="/home/zynq/cnn_linux.py"):
    """把一张 28×28 的图（wdens 输出的 uint8）喂给 PL 上的 CNN

    ★ 2026-10-02 接通：AI 训练负责人交付了波形模型 v1.0
        · 权重    /home/zynq/wave_weights.bin          4480 B
        · 类别    8 类（见本文件 CLASSES，下标顺序与 model_spec.json 一致）
        · MFQ     逐层 201 / 371 / 1390（已写进 cnn_linux.py）
      cnn_linux.py 里的 wave_classify() 就是驱动。

    参数:
        img —— 长度 784 的 uint8 序列（wdens_u8 的输出，值域 0..255）
    返回:
        (类别下标, 类别名, logits) 成功
        (None, 错误信息, None)     失败
    """
    if len(img) != CNN_SIZE * CNN_SIZE:
        return None, "图像尺寸不对：%d，期望 %d" % (len(img), CNN_SIZE * CNN_SIZE)
    if not os.path.exists(cnn_script):
        return None, "找不到 CNN 驱动 %s" % cnn_script
    try:
        sys.path.insert(0, os.path.dirname(cnn_script))
        import importlib
        CL = importlib.import_module(
            os.path.splitext(os.path.basename(cnn_script))[0])
        if not hasattr(CL, "wave_classify"):
            return None, ("cnn_linux.py 里没有 wave_classify() —— "
                          "版本太旧，请更新")
        idx, name, lg = CL.wave_classify(bytes(bytearray(img)))
        return idx, name, lg
    except ImportError as e:
        # /dev/mem 打不开通常就是没在板子上跑（或者不是 root）
        return None, ("接不上加速器：%s（要在板子上、且用 sudo 跑）" % e)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def classify_u8(img, cnn_script="/home/zynq/cnn_linux.py"):
    """同上，但返回中文类别名（给人看）"""
    idx, name, lg = classify_with_cnn(img, cnn_script)
    if idx is None:
        return None, name, None
    cn = dict(CLASSES).get(name, name)
    return idx, cn, lg


# ══════════════════════════════════════════════════════════════════
#  ⑧ 离线自测
# ══════════════════════════════════════════════════════════════════
def selftest():
    """不需要板子 —— 验证整条链在数学上是对的"""
    ok = True

    def chk(cond, msg, detail=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if cond else "✗", msg,
                              ("   " + detail) if detail else ""))
        if not cond:
            ok = False

    print("=" * 78)
    print(" waveform_ai 离线自测（不需要板子）")
    print("=" * 78)

    # ---- ① FFT 正确性：用已知信号验 ----
    print("\n【①】FFT 正确性")
    # 8 点 FFT，输入纯直流 -> 只有 bin0 有值
    re = [1.0] * 8
    im = [0.0] * 8
    fft(re, im)
    chk(abs(re[0] - 8.0) < 1e-6 and all(abs(v) < 1e-6 for v in re[1:]),
        "直流信号 -> bin0 = 8，其余 ≈ 0",
        "bin0=%.3f max_other=%.3e" % (re[0], max(abs(v) for v in re[1:])))

    # 单频：fs=8, 频率=1 -> bin1 有值
    #
    # ★ 注意：cos 是【实信号】，频谱是共轭对称的：
    #     cos(2π·1·t) = (e^{j2πt} + e^{-j2πt}) / 2
    #   ⇒ bin1 和 bin(N-1)=bin7 各有一个峰，幅度【相等】。
    #   所以不能断言"峰在 bin1"，要断言"峰在 bin1 和 bin7，且两者相等"。
    #   （我第一版就写成"峰在 bin1"，然后被浮点误差坑了 —— 其实 FFT 是对的。）
    re = [math.cos(2 * math.pi * i / 8) for i in range(8)]
    im = [0.0] * 8
    fft(re, im)
    mag = [math.sqrt(re[k] ** 2 + im[k] ** 2) for k in range(8)]
    top = sorted(range(8), key=lambda k: -mag[k])[:2]
    chk(set(top) == {1, 7}, "cos(2π·1·t) 的谱峰在 bin1 和 bin7（共轭对称）",
        "实际峰在 bin%s" % top)
    chk(abs(mag[1] - mag[7]) < 1e-9, "bin1 与 bin7 幅度相等",
        "%.6f vs %.6f" % (mag[1], mag[7]))
    chk(max(mag[k] for k in range(8) if k not in (1, 7)) < 1e-9,
        "其余 bin 都 ≈ 0")

    # 和朴素 DFT 对比（随机输入）
    random.seed(7)
    xs = [random.uniform(-1, 1) for _ in range(16)]
    re1 = list(xs)
    im1 = [0.0] * 16
    fft(re1, im1)
    maxerr = 0.0
    for k in range(16):
        sr = si = 0.0
        for n_ in range(16):
            a = -2.0 * math.pi * k * n_ / 16
            sr += xs[n_] * math.cos(a)
            si += xs[n_] * math.sin(a)
        maxerr = max(maxerr, abs(re1[k] - sr), abs(im1[k] - si))
    chk(maxerr < 1e-9, "和朴素 DFT 逐点一致",
        "最大误差 %.2e" % maxerr)

    # ---- ② STFT 维度 ----
    print("\n【②】STFT 维度")
    w = gen_wave("sine", n=4096, freq=10000.0, seed=1)
    frames = stft(w)
    nf, nb = len(frames), len(frames[0])
    expect_nf = (4096 - STFT_WIN) // STFT_HOP + 1
    expect_nb = STFT_WIN // 2 + 1
    chk(nb == expect_nb, "频率 bin 数 = %d" % expect_nb, "实际 %d" % nb)
    chk(nf == expect_nf, "帧数 = %d" % expect_nf, "实际 %d" % nf)

    # ---- ③ 时频图尺寸与量化范围 ----
    print("\n【③】输入图（CNN 输入）")
    img = waveform_to_image(w)
    chk(len(img) == CNN_SIZE * CNN_SIZE,
        "尺寸 = %d×%d = %d 字节" % (CNN_SIZE, CNN_SIZE, CNN_SIZE * CNN_SIZE),
        "实际 %d" % len(img))
    # ★ wdens 是 0..255（uint8），送加速器前才 -128 变 int8。
    #   老的 STFT 路径是 0..127。两条路值域不同，别混。
    if PP_MODE == "wdens":
        chk(max(img) <= 255, "最大值 ≤ 255（uint8 范围）", "max=%d" % max(img))
    else:
        chk(max(img) <= 127, "最大值 ≤ 127（int8 范围）", "max=%d" % max(img))
    chk(max(img) > 0, "不是全零（有特征）", "max=%d" % max(img))

    # ---- ③b ★ wdens 必须和 AI 交付包逐点一致 ----
    print("\n【③b】wdens vs AI 交付包的 preprocess.py")
    _pp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "ai_delivery", "03_源码")
    if os.path.isdir(_pp_path):
        try:
            sys.path.insert(0, _pp_path)
            from common import preprocess as _PP
            bad = 0
            cases = [("sine", 1.0), ("sine", 3.0), ("sine", 8.0),
                     ("square", 2.0), ("square", 5.0), ("triangle", 3.0),
                     ("sawtooth", 4.0), ("noise", 1.0), ("noise", 9.0),
                     ("clipping", 3.0), ("duty_abnormal", 2.0)]
            for i, (kd, kk) in enumerate(cases):
                # 按 K 个周期生成：freq = kk * fs / n
                wv = gen_wave(kd, n=4096, freq=kk * FS_DEFAULT / 4096.0,
                              noise=0.0, seed=i * 3 + 1, duty=0.25)
                s = list(quantize_8bit(wv))
                mine = list(wdens_u8(s))
                th = _PP.capture_to_wdens_u8_pure(s)
                flat = [th[r][c] for r in range(28) for c in range(28)]
                if mine != flat:
                    bad += 1
                    d = max(abs(x - y) for x, y in zip(mine, flat))
                    print("     ✗ %s K=%.1f 最大差 %d" % (kd, kk, d))
            chk(bad == 0, "★ %d 组波形逐点一致（浮点顺序也不能差）" % len(cases),
                "" if bad == 0 else "%d 组不一致" % bad)
        except Exception as e:
            chk(False, "对不上交付包", "%s: %s" % (type(e).__name__, e))
    else:
        print("   - 跳过（没找到 ai_delivery/，只在本机有）")

    # ---- ④ 不同波形的图应该不一样（有区分度）----
    print("\n【④】不同波形的图有没有区分度")
    imgs = {}
    for kind, _ in CLASSES:
        wv = gen_wave(kind, n=4096, freq=10000.0, seed=42)
        imgs[kind] = waveform_to_image(wv)

    # 两两比较：相同波形的不同实例应该更像，不同波形应该差得多
    def dist(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

    # 同一类不同 seed
    same = []
    for kind, _ in CLASSES:
        a = waveform_to_image(gen_wave(kind, n=4096, freq=10000.0, seed=100))
        b = waveform_to_image(gen_wave(kind, n=4096, freq=10000.0, seed=200))
        same.append(dist(a, b))
    # 不同类
    diff = []
    ks = [k for k, _ in CLASSES]
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            diff.append(dist(imgs[ks[i]], imgs[ks[j]]))

    avg_same = sum(same) / len(same)
    avg_diff = sum(diff) / len(diff)
    print("   同类平均距离 = %.2f" % avg_same)
    print("   异类平均距离 = %.2f" % avg_diff)
    chk(avg_diff > avg_same * 1.3,
        "异类差异明显大于同类差异（说明特征图有区分度）",
        "比值 %.2f×" % (avg_diff / max(avg_same, 1e-9)))

    # ---- ⑤ 量化一致性（训练/推理必须同一套）----
    print("\n【⑤】量化可复现性")
    a = waveform_to_image(gen_wave("square", n=4096, seed=5))
    b = waveform_to_image(gen_wave("square", n=4096, seed=5))
    chk(bytes(a) == bytes(b), "同样输入 -> 完全一样的图（可复现）")

    # ---- ⑥ 内存安全（这是踩过坑的）----
    print("\n【⑥】内存安全")
    try:
        import resource
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        before = None
    t0 = time.time()
    for _ in range(10):
        wv = gen_wave("sine", n=4096, seed=3)
        _ = waveform_to_image(wv)
    dt = (time.time() - t0) / 10
    if before is not None:
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        grow = (after - before) / 1024.0
        print("   10 次处理，峰值内存增长 %.1f MB，单次耗时 %.1f ms"
              % (grow, dt * 1000))
        chk(grow < 50, "反复处理不泄漏内存", "增长 %.1f MB" % grow)
    else:
        print("   （这个平台拿不到内存统计）单次耗时 %.1f ms" % (dt * 1000))

    # 处理 4096 点的速度要够快（示波器刷新率考虑）
    chk(dt < 1.0, "单次波形->图像 < 1 秒（够实时用）", "%.1f ms" % (dt * 1000))

    print()
    print("=" * 78)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 78)
    return ok


def demo():
    """看各类波形的特征图（字符画）"""
    print("=" * 78)
    print(" 各类波形的时频图（字符画，越亮越白）")
    print("=" * 78)
    for kind, cn in CLASSES:
        w = gen_wave(kind, n=4096, freq=10000.0, seed=11)
        img = waveform_to_image(w)
        s = image_summary(img)
        print("\n--- %-10s %s ---" % (kind, cn))
        print("    均值 %.1f  非零 %d/%d  min=%d max=%d"
              % (s["mean"], s["nonzero"], len(img), s["min"], s["max"]))
        print(s["art"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="离线自测整条链")
    ap.add_argument("--demo", action="store_true", help="看各类波形的特征图")
    ap.add_argument("--gen-dataset", type=int, default=0,
                    metavar="N", help="每类生成 N 张，输出训练数据集")
    ap.add_argument("--out", default="/home/zynq/wave_dataset",
                    help="数据集输出目录")
    ap.add_argument("--classify", default="", help="用 CNN 推理一个波形文件")
    ap.add_argument("--size", type=int, default=CNN_SIZE)
    a = ap.parse_args()

    if a.selftest:
        return 0 if selftest() else 1
    if a.demo:
        demo()
        return 0
    if a.gen_dataset:
        make_dataset(a.gen_dataset, a.out, size=a.size)
        return 0
    if a.classify:
        raw = open(a.classify, "rb").read()
        samples = array.array("f")
        for b in raw:
            samples.append((b - 128) / 128.0)
        img = waveform_to_image(samples, size=a.size)
        s = image_summary(img, size=a.size)
        print("波形文件 %s（%d 字节）" % (a.classify, len(raw)))
        print("特征图均值 %.1f 非零 %d" % (s["mean"], s["nonzero"]))
        cls, info = classify_with_cnn(img, cnn_script="/home/zynq/cnn_linux.py")
        print("CNN 推理: %s" % (info if cls is None else "类别 %d" % cls))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
