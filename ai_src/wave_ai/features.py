"""
features.py —— 可解释手工特征（视觉分支之外的第二路输入）

★ 为什么要手工特征，而不是"一个更大的 CNN 全包"
  有三类信息在 96×96 密度图上**本质上就画不出来**，但判决又必须用：
     ① 绝对量纲：vpp 是 900 LSB 还是 60 LSB、有没有撞到 0/1023 轨
     ② 窄事件强度：2~10 个采样点的毛刺，落到 96 列里不到 0.25 列
     ③ 周期结构置信度：自相关峰高、边沿数、平坦段占比
   把这些压成 46 维数字直接进融合层，比让 CNN 从像素里"猜"可靠得多，
   而且每一个数字都能在文本里说出来（可解释性 / 调试 / 验收）。

★ 与 quality.py 的分工
   本文件是**快速特征**（约 1.5 ms/帧，供训练与在线推理）；
   quality.py 是**精确测量**（约 15 ms/帧，谐波最小二乘 + 折叠平均 + 边沿插值）。
   两者都从同一份 4096 点原始采样算，互不依赖。
"""
from __future__ import annotations

import math

import numpy as np

from . import dsp
from .config import CLASSES, LSB_TO_V, N_CLASSES

EPS = 1e-12

# ---------------------------------------------------------------------------
# 特征名（顺序冻结；训练/推理/文档共用）
# ---------------------------------------------------------------------------
_BASE_FEATURES = [
    "vpp_norm",            # 峰峰值 / 1024
    "vpp_lsb_log",         # log1p(vpp)
    "mean_norm",           # (mean-511.5)/512
    "std_norm",            # std/512
    "min_norm",            # (p0.5-511.5)/512
    "max_norm",
    "duty",                # 中值电平以上占比
    "f0_log",              # log1p(f0/1000)（kHz 量级）
    "k_log",               # log1p(K)
    "period_conf",         # 自相关峰高（周期性置信度）
    "n_edges_norm",        # 边沿数 / 64
    "cross_irregularity",  # 穿越间隔的变异系数
    "peak_freq_log",       # 最强谱峰频率（kHz，log1p）
    "spec_centroid",       # 谱重心 / Nyquist
    "spec_spread",         # 谱展宽（二阶矩）/ Nyquist
    "spec_flatness",       # 谱平坦度（噪声度）
    "hf_ratio",            # >0.25 Nyquist 能量占比
    "n_peaks_norm",        # 显著谱峰数 / 8
    "h2_ratio",
    "h3_ratio",
    "h4_ratio",
    "thd",                 # 总谐波失真（1~6 次）
    "max_res",             # max|x-medfilt| / (vpp/2)
    "p99_res",
    "outlier_frac",        # |res| > 6*median(res) 的样本占比
    "clip_frac",           # 撞 0/1023 轨的样本占比
    "flat_frac",           # 连续平坦段（>=8 点）占比
    "kurtosis",
    "skewness",
    "edge_sharpness",      # max|diff| / vpp
    "overshoot",           # (max-p99.5)/vpp
    "undershoot",
    "env_mod",             # 包络调制深度
    "env_cycles",          # 包络起伏周期数（整个窗口内）
    "snr_db",              # 由二阶差分中位数估的 SNR（dB/80）
    "low_ratio",           # <0.6 个周期的低频能量占比
    "two_tone",            # 非谐波双峰强度比
    "diff_kurtosis",       # 一阶差分峰度（毛刺/噪声）
    "ac2",                 # 自相关在 2 倍周期处的高度
    "asymmetry",           # 上下半波面积不对称度
    "half_drift",          # 前后半窗均值差 / vpp（工频漂移的最强判据）
    "slope_norm",          # 整窗线性趋势 / vpp
]
FEATURE_NAMES = _BASE_FEATURES + ["lp_%s" % c for c in CLASSES] + ["lp_available"]
FEAT_DIM = len(FEATURE_NAMES)
N_BASE = len(_BASE_FEATURES)


def _safe(v, default=0.0, lo=-1e6, hi=1e6):
    try:
        f = float(v)
    except Exception:
        return default
    if not np.isfinite(f):
        return default
    return float(np.clip(f, lo, hi))


def _flat_fraction(x):
    d = np.abs(np.diff(x))
    b = (d < 0.75).astype(np.int8)
    p = np.r_[0, b, 0]
    dd = np.diff(p)
    starts = np.where(dd == 1)[0]
    ends = np.where(dd == -1)[0]
    if len(starts) == 0:
        return 0.0
    lens = ends - starts
    return float(lens[lens >= 8].sum()) / float(len(x))


def extract_features(raw, fs_eff: float, local_probs=None):
    """返回 (feat (FEAT_DIM,) float32, info dict)。

    info 里是给响应体/文本用的测量值（JSON 安全，不可测为 None）。
    """
    x = np.asarray(raw, dtype=np.float64)
    n = len(x)
    vpp, lo, hi = dsp.robust_vpp(x)
    mean = float(x.mean())
    std = float(x.std())
    mid = dsp.mid_level(x)

    period, pconf = 0.0, 0.0
    k_cycles, f0, r2, _peak_amp = dsp.estimate_tonal(x, fs_eff)
    valid_p = bool(np.isfinite(k_cycles) and k_cycles >= 1.0)
    if valid_p:
        period = float(n) / k_cycles
        pconf = float(np.clip(r2, 0.0, 1.0))
    else:
        f0 = float("nan")
        k_cycles = float("nan")
        pconf = 0.0

    mag = dsp.spectrum(x)
    peaks = dsp.spectral_peaks(mag, n, fs_eff, max_peaks=4)

    # ---- 谐波幅度（FFT 峰值，±1 bin 内取最大）----
    amps = np.zeros(6)
    if valid_p and f0 > 0:
        for h in range(1, 7):
            b = h * f0 * n / fs_eff
            i = int(round(b))
            if 1 <= i < len(mag) - 1:
                amps[h - 1] = float(np.max(mag[max(1, i - 1):i + 2]))
    thd = float(np.sqrt(np.sum(amps[1:] ** 2)) / max(amps[0], EPS)) if amps[0] > 0 else 0.0

    # ---- 残差 / 噪声 / 轨 ----
    res = dsp.residual(x, 25)
    amp = max(0.5 * vpp, 1.0)
    med_res = float(np.median(res))
    max_res = float(res.max()) / amp
    p99_res = float(np.percentile(res, 99)) / amp
    outlier_frac = float(np.mean(res > max(6.0 * med_res, 6.0)))
    clip_frac = float(np.mean((x <= 2) | (x >= 1021)))
    flat_frac = _flat_fraction(x)

    d2 = np.diff(x, 2)
    mad2 = float(np.median(np.abs(d2 - np.median(d2)))) if len(d2) else 0.0
    sigma_n = max(1.4826 * mad2 / math.sqrt(6.0), 1e-6)
    snr = float(np.clip(10.0 * math.log10(max(std ** 2, EPS) / (sigma_n ** 2)), 0.0, 80.0))

    d1 = np.diff(x)
    edge_sharp = float(np.max(np.abs(d1)) / max(vpp, 1.0)) if len(d1) else 0.0
    overshoot = float((x.max() - hi) / max(vpp, 1.0))
    undershoot = float((lo - x.min()) / max(vpp, 1.0))

    # ---- 边沿/占空比 ----
    s = (x >= mid).astype(np.int8)
    chg = np.where(np.diff(s) != 0)[0]
    n_edges = int(len(chg))
    duty = float(np.mean(s))
    if n_edges >= 3:
        gaps = np.diff(chg).astype(np.float64)
        cross_irr = float(np.std(gaps) / max(np.mean(gaps), EPS))
    else:
        cross_irr = 0.0

    # ---- 谱形 ----
    if len(mag) > 1:
        p = mag[1:] ** 2
        tot = float(p.sum())
        if tot > 0:
            freqs = np.arange(1, len(mag)) / float(n)
            centroid = float(np.sum(freqs * p) / tot)
            spread = float(np.sqrt(np.sum((freqs - centroid) ** 2 * p) / tot))
            flatness = float(np.exp(np.mean(np.log(p + EPS))) / (np.mean(p) + EPS))
            hf = float(p[freqs > 0.25].sum() / tot)
        else:
            centroid = spread = flatness = hf = 0.0
    else:
        centroid = spread = flatness = hf = 0.0
    n_peaks = min(len(peaks), 8)

    # ---- 包络（调幅 / 工频） ----
    env = dsp.envelope(x)
    if len(env) > 32:
        k = max(3, int(round((period if valid_p else n / 4.0) / 16.0)))
        kern = np.ones(k) / k
        env_s = np.convolve(env, kern, mode="same")
        e_lo, e_hi = np.percentile(env_s, [5, 95])
        env_mod = float((e_hi - e_lo) / max(e_hi + e_lo, EPS))
        es = np.abs(np.fft.rfft(env_s - env_s.mean()))
        env_cycles = float(np.argmax(es[1:]) + 1) if len(es) > 2 else 0.0
    else:
        env_mod, env_cycles = 0.0, 0.0

    # ---- 低频能量（工频干扰/漂移）----
    if valid_p:
        cut = max(2, int(round(0.6 * k_cycles)))
        cut = min(cut, len(mag) - 1)
        p_all = float(np.sum(mag[1:] ** 2)) + EPS
        low_ratio = float(np.sum(mag[1:cut] ** 2) / p_all)
    else:
        low_ratio = 0.0

    # ---- 双频（非谐波双峰）----
    two_tone = 0.0
    if len(peaks) >= 2 and peaks[0][0] > 0:
        f1 = peaks[0][0]
        for f2, a2, _ in peaks[1:]:
            if f2 <= f1 * 1.2:
                continue
            r = f2 / f1
            if abs(r - round(r)) > 0.15:
                two_tone = float(min(a2 / max(peaks[0][1], EPS), 3.0) / 3.0)
                break

    ac2 = 0.0
    if valid_p:
        from .dsp import to_float
        xx = to_float(x) - mean
        lag = int(round(2 * period))
        if 0 < lag < n - 4:
            ac2 = float(np.dot(xx[:-lag], xx[lag:]) / max(np.dot(xx, xx), EPS))

    upper = x[x >= mid]
    lower = x[x < mid]
    asym = float(abs((upper.mean() - mid) - (mid - lower.mean())) /
                 max(0.5 * vpp, EPS)) if len(upper) and len(lower) else 0.0

    # ---- 低频漂移（工频干扰）：前后半窗均值差 + 整窗线性趋势 ----
    # ★ 0.06~0.3 个周期的工频漂移在频域里落在 bin 0~1，会被"去均值"吃掉，
    #   但在时域里表现为"前半窗偏高、后半窗偏低" —— 这个判据比频谱更可靠。
    h = n // 2
    half_drift = float(abs(x[h:].mean() - x[:h].mean()) / max(vpp, 1.0))
    tt = (np.arange(n, dtype=np.float64) - 0.5 * n) / float(n)
    slope = float(np.dot(tt, x - mean) / max(np.dot(tt, tt), EPS))
    slope_norm = float(slope / max(vpp, 1.0))

    feats = [
        vpp / 1024.0, math.log1p(vpp), (mean - 511.5) / 512.0, std / 512.0,
        (lo - 511.5) / 512.0, (hi - 511.5) / 512.0, duty,
        math.log1p(f0 / 1000.0) if valid_p else 0.0,
        math.log1p(k_cycles) if valid_p else 0.0,
        pconf,
        min(n_edges, 200) / 64.0, cross_irr,
        math.log1p(peaks[0][0] / 1000.0) if peaks else 0.0,
        centroid, spread, flatness, hf,
        n_peaks / 8.0,
        min(amps[1] / max(amps[0], EPS), 3.0), min(amps[2] / max(amps[0], EPS), 3.0),
        min(amps[3] / max(amps[0], EPS), 3.0), min(thd, 3.0),
        min(max_res, 4.0), min(p99_res, 4.0), min(outlier_frac, 1.0),
        clip_frac, flat_frac, dsp.kurtosis(x) / 10.0, dsp.skewness(x),
        min(edge_sharp, 4.0), min(max(overshoot, 0.0), 1.0), min(max(undershoot, 0.0), 1.0),
        min(env_mod, 1.5), min(env_cycles, 16.0) / 16.0, snr / 80.0,
        low_ratio, two_tone, dsp.kurtosis(d1) / 10.0, ac2, asym,
        half_drift, slope_norm,
    ]

    if local_probs is None:
        # ★ 端侧没给概率时，填"无信息的均匀先验 1/8"而不是全 0：
        #   全 0 是一个模型训练时很少见到的分布（概率和=0），会被当成"端侧说全都不可能"；
        #   均匀 1/8 + lp_available=0 才是"端侧没意见"的正确语义。
        lp = np.zeros(N_CLASSES)
        lp[:8] = 1.0 / 8.0
        lp_ok = 0.0
    else:
        lp = np.asarray(local_probs, dtype=np.float64).reshape(-1)
        if lp.size != N_CLASSES:
            lp = np.resize(lp, N_CLASSES)
        lp = np.clip(np.nan_to_num(lp, nan=0.0, posinf=0.0, neginf=0.0), 0.0, None)
        ssum = float(lp.sum())
        lp = lp / ssum if ssum > 0 else np.zeros(N_CLASSES)
        lp_ok = 1.0
    vec = np.asarray(feats + list(lp) + [lp_ok], dtype=np.float32)
    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
    assert vec.size == FEAT_DIM, (vec.size, FEAT_DIM)

    info = {
        "freq_hz": _safe(f0) if valid_p else None,
        "vpp_lsb": _safe(vpp),
        "vpp_v": _safe(vpp * LSB_TO_V),
        "vmax_v": _safe((hi - 511.5) * LSB_TO_V),
        "vmin_v": _safe((lo - 511.5) * LSB_TO_V),
        "mean_v": _safe((mean - 511.5) * LSB_TO_V),
        "duty_pct": _safe(100.0 * duty),
        "K": _safe(k_cycles) if valid_p else None,
        "period_conf": _safe(pconf),
        "snr_db_fast": _safe(snr),
        "thd_pct_fast": _safe(100.0 * thd),
        "n_edges": n_edges,
        "clip_frac": _safe(clip_frac),
        "flat_frac": _safe(flat_frac),
        "env_mod": _safe(env_mod),
        "env_cycles": _safe(env_cycles),
    }
    return vec, info


# ---------------------------------------------------------------------------
# 归一化（训练集统计量，随模型一起落盘）
# ---------------------------------------------------------------------------
def normalize(feat, mean, std):
    a = np.asarray(feat, dtype=np.float32)
    return ((a - np.asarray(mean, dtype=np.float32)) /
            np.maximum(np.asarray(std, dtype=np.float32), 1e-6)).astype(np.float32)


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    from .hw_sim import synth
    for lab in ("square", "noise", "glitch", "am"):
        raw, par = synth(lab, 4, rng, chunk=4)
        v, info = extract_features(raw[0], 2e6)
        print(lab, v.shape, "vpp=%.0f K=%.2f f0=%.1f snr=%.1f thd=%.2f%%"
              % (info["vpp_lsb"], info["K"] or -1, info["freq_hz"] or -1,
                 info["snr_db_fast"], info["thd_pct_fast"]))
