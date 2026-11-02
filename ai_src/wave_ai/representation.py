"""
representation.py —— 4096 点采集 → 96×96×3 视觉输入

三个通道各回答一个问题，合起来才是"多模态"里的视觉那一半：

  ch0  dens_abs  : 绝对幅度密度图（行 = ADC 码值 0~1023，0 行 = 最高电平）
                   —— 保留"有没有撞到量程/轨"这类绝对信息
  ch1  dens_norm : 每帧 min-max 自归一化密度图
                   —— 小信号（vpp 只有几十 LSB）也能看清形状
  ch2  resid     : 局部残差能量图（|x - 中值滤波(x)| 累加到 (幅度行,时间列)，按 0.5*vpp 归一）
                   —— 专门给"窄事件"用：毛刺、窄脉冲、陡边沿、噪声底

★ 为什么 96×96 而不是端侧的 28×28
   96 列 × 42.7 采样/列。真实工况 K≈2（1 kHz @ dec=10）时，
   一个周期有 48 列，方波的占空比、三角波的非线性、调幅包络的起伏才画得出来；
   28 列时一个周期只有 14 列，形状信息基本被压平。
   ★ 但必须诚实：42.7 采样/列 ⇒ 单列 = 21 µs。
     所以"上升沿 1.2 µs"在密度图上仍然只有 0.06 列 —— 边沿细节看不见，
     这也是为什么上升时间必须从**原始 4096 点**算（quality.py），而不是看图。

★ 归一化口径
   密度 = 列内直方图计数 / 列宽，再开方（方差稳定化），再按该帧最大值归一到 255。
   ch2 按 0.5*vpp 归一（而不是按自身最大值），保证不同幅度信号的"残差强度"可比。
"""
from __future__ import annotations

import numpy as np

from .config import ADC_MAX, CAP_LEN, IMG, N_CHANNELS

ROWS = IMG
COLS = IMG


def _col_bounds():
    """96 列尽量均分 4096 点：前 64 列 43 点，后 32 列 42 点"""
    base, rem = divmod(CAP_LEN, COLS)
    out = []
    a = 0
    for c in range(COLS):
        w = base + (1 if c < rem else 0)
        out.append((a, a + w))
        a += w
    return tuple(out)


COL_BOUNDS = _col_bounds()
COL_WIDTHS = np.array([b - a for a, b in COL_BOUNDS], dtype=np.float64)
_COL_STARTS = np.array([a for a, _ in COL_BOUNDS], dtype=np.int64)
# 每个采样点属于哪一列（4096,）—— 用于把"列直方图"合并成一次 bincount
_SAMPLE_COL = np.repeat(np.arange(COLS), COL_WIDTHS.astype(np.int64))


def _density(rows, n, weights=None, nbins=ROWS):
    """rows (n, CAP_LEN) 整数行号 → (n, nbins, COLS) 的 sqrt 压缩密度

    ★ 性能：96 列 × 3 个通道逐个 bincount 太慢（每批 288 次），
      这里把 (样本, 列, 行) 压成一维索引，整批只做 1 次 bincount。
    """
    base = (np.arange(n, dtype=np.int64) * (COLS * nbins))[:, None]
    idx = (base + _SAMPLE_COL[None, :] * nbins + rows).ravel()
    if weights is None:
        acc = np.bincount(idx, minlength=n * COLS * nbins)
    else:
        acc = np.bincount(idx, weights=np.asarray(weights, dtype=np.float64).ravel(),
                          minlength=n * COLS * nbins)
    img = acc.reshape(n, COLS, nbins).transpose(0, 2, 1)
    img = img / COL_WIDTHS[None, None, :]
    return np.sqrt(np.clip(img, 0.0, None))


def _norm_u8(img):
    mx = img.max(axis=(1, 2), keepdims=True)
    mx[mx <= 0] = 1.0
    return np.rint(np.clip(img / mx, 0.0, 1.0) * 255.0).astype(np.uint8)


def to_images(raw2d) -> np.ndarray:
    """(N,4096) uint16/uint8 → (N,3,96,96) uint8"""
    s = np.asarray(raw2d)
    if s.ndim == 1:
        return to_images(s[None, :])[0]
    if s.ndim != 2 or s.shape[1] != CAP_LEN:
        raise ValueError("expect (N,%d), got %s" % (CAP_LEN, s.shape))
    n = s.shape[0]
    x = s.astype(np.int32)

    # ---- ch0：绝对幅度（1024 码 → 96 行）----
    rows_abs = (ADC_MAX - x) * ROWS // (ADC_MAX + 1)          # 0 行 = 最高电平
    np.clip(rows_abs, 0, ROWS - 1, out=rows_abs)
    ch0 = _norm_u8(_density(rows_abs, n))

    # ---- ch1：每帧自归一化幅度 ----
    lo = np.percentile(x, 0.5, axis=1, keepdims=True)
    hi = np.percentile(x, 99.5, axis=1, keepdims=True)
    span = np.maximum(hi - lo, 1.0)
    rows_norm = np.rint((hi - x) / span * (ROWS - 1)).astype(np.int32)
    np.clip(rows_norm, 0, ROWS - 1, out=rows_norm)
    ch1 = _norm_u8(_density(rows_norm, n))

    # ---- ch2：局部残差（窄事件）----
    # 每列取 |x - 滑动均值| 的【最大值】，先减去 1.8 倍本帧中位数（自适应噪声底），
    # 再按 vpp 归一：只保留"明显高于自身噪声底"的窄事件。
    #   · 毛刺/窄脉冲 = 一根很亮的条（列位置即事件时刻；幅度信息在亮度里）
    #   · 陡边沿 = 每个跳变一根亮条（方波因此有规律的两条/周期）
    #   · 纯噪声 = 基底整体抬高后被减掉 ⇒ 通道很暗（它没有"窄事件"）
    #   · 小信号 = 噪声比 vpp 大，通道自然偏亮（信噪比低本就该看得见）
    # ★ 不用"按列平均"：1 个采样点的毛刺会被 43 点的列宽摊薄到 1/43，
    #   开方后只剩 0.15 —— 正好把最难的那类信号淹掉。最大值语义才是对的。
    from scipy.ndimage import uniform_filter1d
    # 25 点滑动均值（dec=10 时 12.5 µs）：能抓住 2~12 点的毛刺与 1~3 点的陡边沿，
    # 又不会把正弦/三角的缓慢弯曲当成事件（那只是低频形状，ch0/ch1 已经画了）。
    # ★ 用均值而不是中值：中值滤波 128×4096 要 141 ms（训练每批都算，太贵），
    #   均值滤波 2 ms，且对"稀疏尖峰"同样敏感（尖峰只把均值抬高 w/25）。
    med = uniform_filter1d(x.astype(np.float64), size=25, axis=1, mode="nearest")
    res = np.abs(x - med)
    vpp = np.maximum(hi[:, 0] - lo[:, 0], 8.0)
    colmax = np.maximum.reduceat(res, _COL_STARTS, axis=1)
    # ★ 自适应基底：列最大值天然会被"43 点里的最大噪声"抬高（≈2.6σ），
    #   直接除以 vpp 会让所有通道都挂一层灰雾。先减掉 1.8 倍中位数，
    #   只保留**显著高于本帧噪声底**的窄事件 ⇒ 通道变稀疏，毛刺/边沿才跳出来。
    floor = 1.8 * np.median(colmax, axis=1, keepdims=True)
    scale = vpp[:, None]
    v = np.clip((colmax - floor) / scale, 0.0, 1.0)
    ch2v = np.rint(np.sqrt(v) * 255.0).astype(np.uint8)
    ch2 = np.repeat(ch2v[:, None, :], ROWS, axis=1)

    out = np.stack([ch0, ch1, ch2], axis=1).astype(np.uint8)
    assert out.shape == (n, N_CHANNELS, IMG, IMG)
    return out


def to_model_input(images_u8) -> np.ndarray:
    """uint8 (N,3,H,W) → float32 (N,3,H,W) ∈ [-1,1]"""
    a = np.asarray(images_u8, dtype=np.float32)
    return a * (2.0 / 255.0) - 1.0


def describe() -> dict:
    return {
        "shape": [N_CHANNELS, IMG, IMG],
        "cols": COLS,
        "rows": ROWS,
        "samples_per_col": [int(w) for w in COL_WIDTHS],
        "channels": {
            "0": "dens_abs: 绝对幅度密度（行=ADC 0~1023，0 行=高电平）",
            "1": "dens_norm: 每帧自归一化幅度密度（小信号形状）",
            "2": "resid: |x-medfilt9(x)| 按 (幅度行,时间列) 累加 / (0.5*vpp)（窄事件）",
        },
    }


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    from .hw_sim import synth
    raw, par = synth("square", 4, rng, chunk=4)
    img = to_images(raw)
    print("shape", img.shape, img.dtype, "range", img.min(), img.max())
    print("per-channel mean", img.mean(axis=(0, 2, 3)))
    print("col widths", COL_WIDTHS[:3], "...", COL_WIDTHS[-3:], "sum", COL_WIDTHS.sum())
