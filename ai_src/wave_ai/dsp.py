"""
dsp.py —— 共享信号处理内核（特征、质量评估、异常规则都用它）

设计原则：
  · 全部纯 numpy/scipy，无状态、可单测
  · 对"只有 1.5~3 个周期"的真实工况也要稳健（不能用"长窗 FFT 分辨率"的假设）
  · 任何估计都给出一个 0~1 的置信度，低置信度时上层必须报 null 而不是瞎猜
"""
from __future__ import annotations

import math

import numpy as np

EPS = 1e-12


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
def to_float(raw):
    return np.asarray(raw, dtype=np.float64)


def robust_vpp(x):
    """稳健峰峰值（避开单点毛刺把 vpp 拉爆）"""
    lo, hi = np.percentile(x, [0.5, 99.5])
    return float(hi - lo), float(lo), float(hi)


def mid_level(x):
    _, lo, hi = robust_vpp(x)
    return 0.5 * (lo + hi)


def moving_median(x, k=25):
    """滑动中值（只在离线分析/质量评估里用；训练批处理用 representation 的均值版）"""
    from scipy.ndimage import median_filter
    return median_filter(x, size=int(k), mode="nearest")


def residual(x, k=25):
    """局部残差：|x - 滑动均值(x)|。对毛刺/窄脉冲/陡边沿敏感，对平滑波形不敏感。

    ★ k=25（不是 9）：dec=10 时 = 12.5 µs，正好覆盖"2~12 点毛刺"的整个宽度；
      k 太小时滑窗会跟着毛刺一起走，残差反而消失（实测 k=5 时毛刺残差 < 0.2 vpp）。
    ★ 与 representation ch2 用同一算子（均值而非中值），保证"图上看到的"和
      "特征里算的"是同一个量。
    """
    from scipy.ndimage import uniform_filter1d
    x = to_float(x)
    return np.abs(x - uniform_filter1d(x, size=int(k), axis=-1, mode="nearest"))


def hann(n):
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / float(n))


def spectrum(x, detrend=True):
    """Hann 窗幅度谱（单边，已按窗增益归一：正弦幅度 ≈ 谱峰 × 2）"""
    x = to_float(x)
    if detrend:
        x = x - x.mean()
    w = hann(len(x))
    X = np.fft.rfft(x * w)
    mag = np.abs(X) * 2.0 / np.sum(w)
    return mag


# ---------------------------------------------------------------------------
# 周期估计（自相关 + 抛物线插值）
# ---------------------------------------------------------------------------
def estimate_period(x, k_min=1.2, k_max=64.0):
    """返回 (period_samples, confidence)；confidence = 归一化自相关峰值高度。

    ★ 为什么用"过零后的第一个局部极大"而不是全局最大：
      方波/锯齿的自相关在 lag→0 处天然接近 1（波形局部平滑），
      直接取全局最大会永远选中最小 lag（实测把 K=64 当成真周期）。
      正确做法：先找自相关第一次变负的位置（半个周期），再取之后的第一个局部峰。
    ★ 单次阶跃/孤立脉冲/极低频漂移的自相关**不穿过零点** ⇒ 直接判为无周期，
      这正是我们要的"非周期置信度"。
    """
    x = to_float(x)
    n = len(x)
    if n < 64:
        return float("nan"), 0.0
    x = x - x.mean()
    var = float(np.dot(x, x))
    if var <= EPS:
        return float("nan"), 0.0

    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    X = np.fft.rfft(x, nfft)
    ac = np.fft.irfft(X * np.conj(X), nfft)[:n]
    ac = ac / ac[0]

    lo = max(2, int(n / float(k_max)))
    hi = min(n - 2, int(n / float(k_min)))
    if hi <= lo + 4:
        return float("nan"), 0.0

    seg = ac[lo:hi + 1]
    neg = np.where(seg <= 0.0)[0]
    if len(neg) == 0:
        return float("nan"), 0.0
    z = int(neg[0]) + lo                      # 第一次过零（≈ 半周期）

    # 过零后的第一个局部极大
    best_i, best_v = -1, -1.0
    for i in range(z + 1, hi):
        if ac[i] >= ac[i - 1] and ac[i] > ac[i + 1] and ac[i] > 0.12:
            best_i, best_v = i, float(ac[i])
            break
    if best_i < 0:
        return float("nan"), 0.0

    lag = float(best_i)
    if 0 < best_i < len(ac) - 1:
        y0, y1, y2 = float(ac[best_i - 1]), float(ac[best_i]), float(ac[best_i + 1])
        denom = (y0 - 2.0 * y1 + y2)
        if abs(denom) > 1e-12:
            lag += 0.5 * (y0 - y2) / denom
    return lag, float(np.clip(best_v, 0.0, 1.0))


def period_to_f0(period, fs):
    if not np.isfinite(period) or period <= 0:
        return float("nan")
    return float(fs) / float(period)


def estimate_tonal(x, fs, k_min=1.0, k_max=64.0, n_harm=4):
    """谱峰定基频 + 谐波拟合 R² 定置信度，返回 (K, f0_hz, r2, amp)。

    ★ 为什么不用纯自相关：
      方波/三角的自相关在 lag→0 天然接近 1，取全局最大会选中最小 lag；
      取"过零后第一个局部极大"又会被噪声小鼓包骗到谐波上。
    ★ 为什么用谐波拟合 R² 做置信度：
      它直接回答"这段波形能不能用 1 个基频 + 少量谐波解释"。
      正弦/方波/调幅 R²≈0.9+；阶跃/孤立脉冲/噪声 R² 低。
    ★ K/f0 一律返回（不做门限）：低置信度由调用方通过 r2 决定是否采信，
      这样 FM/双频这类"有主峰但不是单基频"的类别也不会丢掉载波频率信息。
    """
    x = to_float(x)
    n = len(x)
    mag = spectrum(x)
    i0 = max(1, int(math.floor(k_min)))
    i1 = min(len(mag) - 2, int(math.floor(k_max)))
    if i1 <= i0:
        return float("nan"), float("nan"), 0.0, 0.0
    i = i0 + int(np.argmax(mag[i0:i1 + 1]))
    y0, y1, y2 = float(mag[i - 1]), float(mag[i]), float(mag[i + 1])
    d = y0 - 2.0 * y1 + y2
    off = 0.5 * (y0 - y2) / d if abs(d) > 1e-12 else 0.0
    k = float(i) + float(np.clip(off, -0.5, 0.5))
    f0 = k * float(fs) / float(n)
    if not (f0 > 0) or not np.isfinite(f0):
        return float("nan"), float("nan"), 0.0, 0.0
    fit = harmonic_fit(x, f0, fs, n_harm)
    return k, f0, float(fit["r2"]), float(y1)


# ---------------------------------------------------------------------------
# 谐波最小二乘拟合（少周期下比 FFT 准确得多）
# ---------------------------------------------------------------------------
def harmonic_fit(x, f0, fs, n_harm=6):
    """在已知基频下最小二乘拟合 DC + H 个谐波。

    返回 dict：
        amps   (H,)  各次谐波幅度
        phases (H,)
        fitted (n,)
        resid  (n,)
        r2     拟合优度（相对 AC 能量）
    """
    x = to_float(x)
    n = len(x)
    out = {"amps": np.zeros(n_harm), "phases": np.zeros(n_harm),
           "fitted": np.zeros(n), "resid": x - x.mean(), "r2": 0.0}
    if not np.isfinite(f0) or f0 <= 0 or f0 >= fs * 0.5:
        return out
    t = np.arange(n, dtype=np.float64) / float(fs)
    cols = [np.ones(n)]
    for h in range(1, n_harm + 1):
        w = 2.0 * np.pi * h * f0 * t
        cols.append(np.cos(w))
        cols.append(np.sin(w))
    A = np.stack(cols, axis=1)
    try:
        coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    except np.linalg.LinAlgError:
        return out
    fitted = A @ coef
    resid = x - fitted
    ac = float(np.var(x))
    r2 = 1.0 - float(np.var(resid)) / max(ac, EPS)
    amps = np.zeros(n_harm)
    phases = np.zeros(n_harm)
    for h in range(n_harm):
        c, s = coef[1 + 2 * h], coef[2 + 2 * h]
        amps[h] = math.hypot(c, s)
        phases[h] = math.atan2(-s, c)
    out.update(amps=amps, phases=phases, fitted=fitted, resid=resid,
               r2=float(np.clip(r2, 0.0, 1.0)))
    return out


def refine_f0(x, f0, fs, n_harm=6, span=0.01, iters=12):
    """在 f0 附近做黄金分割式细搜，最大化谐波拟合 R²。

    ★★ 注意：这个估计量对**非带限**波形（方波/锯齿）有系统性偏低偏差。
       实测 4.000 周期的方波会被拉到 3.989（-0.26%），因为截断谐波基 + 非周期
       基函数可以多吸收一点边沿能量。0.26% 的周期误差会让 4 个周期的折叠平均
       糊掉约 1% 个周期 —— 上升时间会被从 1.1 µs 测成 4.8 µs。
       ⇒ 折叠/边沿测量请用 period_from_crossings()，本函数只用于"给 THD 一个
         初始基频"或诊断。
    """
    if not np.isfinite(f0) or f0 <= 0:
        return f0, 0.0
    lo, hi = f0 * (1.0 - span), f0 * (1.0 + span)
    gr = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc = harmonic_fit(x, c, fs, n_harm)["r2"]
    fd = harmonic_fit(x, d, fs, n_harm)["r2"]
    for _ in range(iters):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = harmonic_fit(x, c, fs, n_harm)["r2"]
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = harmonic_fit(x, d, fs, n_harm)["r2"]
    best = 0.5 * (a + b)
    fit = harmonic_fit(x, best, fs, n_harm)
    return float(best), float(fit["r2"])


def _crossings(x, level, rising=True, hyst=0.0):
    """过电平点（线性插值，返回小数采样下标）。

    ★★ hyst（迟滞/Schmitt）不是可选项：
      少周期正弦过中点时斜率只有 ~2 LSB/采样点，而噪声有 13 LSB，
      在中点附近会来回穿越十几次。不设迟滞时，一个下降沿的"抖动尾巴"
      会被判成上升沿 —— 实测把 K=3.9 的正弦测成 K=7.8（半周期），
      进而 THD 报成 282%。
      迟滞取 2~3% 峰峰值即可：对方波陡边沿的定时影响 <0.05 个采样点。
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    out = []
    if n < 3:
        return np.asarray(out, dtype=np.float64)
    h = float(max(0.0, hyst))
    armed = True
    last_ref = None          # 最近一次"越过 level"的点（用于插值）
    for i in range(n):
        v = x[i]
        if rising:
            if v <= level:
                last_ref = i
                if v <= level - h:
                    armed = True
            elif armed and v >= level + h and last_ref is not None and last_ref < i:
                j = last_ref
                a, b = x[j], x[j + 1]
                t = j + (level - a) / (b - a) if b > a else float(j)
                out.append(float(t))
                armed = False
        else:
            if v >= level:
                last_ref = i
                if v >= level + h:
                    armed = True
            elif armed and v <= level - h and last_ref is not None and last_ref < i:
                j = last_ref
                a, b = x[j], x[j + 1]
                t = j + (a - level) / (a - b) if a > b else float(j)
                out.append(float(t))
                armed = False
    return np.asarray(out, dtype=np.float64)


def _hyst_of(x, frac=0.03, nsig=3.0):
    """迟滞门限 = max(3% 峰峰值, 3σ 噪声)。

    ★ 只用 3% 峰峰值不够：小信号（vpp 只有 140 LSB）时 3% 才 4 LSB，
      而噪声 13 LSB ⇒ 中点附近照样抖出十几次假穿越（实测 THD 报 492%）。
      用二阶差分的中位数估噪声 σ（对稀疏边沿稳健），两者取大。
    """
    x = np.asarray(x, dtype=np.float64)
    vpp, _, _ = robust_vpp(x)
    d2 = np.diff(x, 2)
    sigma = 0.0
    if len(d2) > 8:
        mad = float(np.median(np.abs(d2 - np.median(d2))))
        sigma = 1.4826 * mad / math.sqrt(6.0)
    return float(max(frac * vpp, nsig * sigma))


def period_from_crossings(x, level=None, expected=None, max_cv=0.20):
    """用过零点间隔估计周期（比谱估计准一个量级，且对非带限波形无偏）。

    返回 (period_samples, n_intervals, cv)。

    ★★ 必须做"去抖"（debounce）：
      少周期正弦过中点时斜率只有 ~1 LSB/采样点，而噪声有 13 LSB，
      于是在中点附近来回穿越十几次 —— 直接取间隔中位数会把"抖动间隔"
      当成周期（实测正弦 THD 因此算成 428%）。
      给了 expected（谱估计周期）时，强制相邻接受点至少相隔 0.5 个周期。
    """
    x = to_float(x)
    if level is None:
        level = mid_level(x)
    h = _hyst_of(x)
    up = _crossings(x, level, True, h)
    if len(up) < 2:
        return float("nan"), 0, 1.0
    if expected is not None and np.isfinite(expected) and expected > 4:
        gap = 0.5 * float(expected)
        keep = [float(up[0])]
        for t in up[1:]:
            if float(t) - keep[-1] >= gap:
                keep.append(float(t))
        up = np.asarray(keep, dtype=np.float64)
    if len(up) < 2:
        return float("nan"), 0, 1.0
    d = np.diff(up)
    d = d[d > 2]
    if len(d) == 0:
        return float("nan"), 0, 1.0
    med = float(np.median(d))
    keepd = d[np.abs(d - med) < 0.25 * med]
    if len(keepd) == 0:
        return float("nan"), len(d), 1.0
    cv = float(np.std(keepd) / max(np.mean(keepd), EPS))
    if cv > max_cv:
        return float("nan"), len(keepd), cv
    return float(np.median(keepd)), len(keepd), cv


# ---------------------------------------------------------------------------
# 折叠平均（一个周期）
# ---------------------------------------------------------------------------
def fold_period(x, period, nbins=512):
    """把整段缓冲按周期折叠成一个平均周期（相位分箱平均）。

    返回 (phase, wave)：phase ∈ [0,1)，wave 为该相位上的平均值。
    ★ 少周期时它同时是"降噪平均"：2 个周期能把噪声压低 3 dB。
    """
    x = to_float(x)
    n = len(x)
    if not np.isfinite(period) or period < 2:
        return None, None
    ph = np.mod(np.arange(n, dtype=np.float64), period) / period
    idx = np.clip((ph * nbins).astype(np.int64), 0, nbins - 1)
    s = np.bincount(idx, weights=x, minlength=nbins)
    c = np.bincount(idx, minlength=nbins).astype(np.float64)
    wave = np.where(c > 0, s / np.maximum(c, 1.0), np.nan)
    # 线性插值补空箱（★ 不做平滑：3 点平滑会把 1 个采样点的边沿抹成 3 个，
    # 直接把 0.7 µs 的上升时间测成 3 µs —— 这是实测踩过的坑）
    if np.isnan(wave).any():
        good = ~np.isnan(wave)
        if good.sum() < 4:
            return None, None
        xi = np.arange(nbins)
        wave = np.interp(xi, xi[good], wave[good], period=nbins)
    phase = (np.arange(nbins) + 0.5) / nbins
    return phase, wave


# ---------------------------------------------------------------------------
# 边沿测量（10%~90%）
# ---------------------------------------------------------------------------
def _crossing(x, level, rising, start=0):
    """线性插值找穿越点（返回小数下标）；找不到返回 None"""
    n = len(x)
    for i in range(start + 1, n):
        a, b = x[i - 1], x[i]
        if rising and a < level <= b:
            return i - 1 + (level - a) / max(b - a, EPS)
        if (not rising) and a > level >= b:
            return i - 1 + (a - level) / max(a - b, EPS)
    return None


def _phase_at(pr, idx):
    """数组下标（可为小数）→ 相位（线性插值）"""
    if idx is None:
        return None
    i0 = int(math.floor(idx))
    i1 = min(i0 + 1, len(pr) - 1)
    f = idx - i0
    return float(pr[i0] * (1.0 - f) + pr[i1] * f)


def edge_metrics(phase, wave, vpp):
    """从折叠周期里测边沿/过冲（时间单位 = 周期，由调用方换算 µs）。

    返回 dict：
        rise_cycles / fall_cycles : 10%~90% 边沿宽度（单位为"个周期"）
        overshoot_pct / undershoot_pct : 相对 5%~95% 幅度
        duty_pct : 中值电平以上占比
    """
    out = {"rise_cycles": None, "fall_cycles": None,
           "overshoot_pct": None, "undershoot_pct": None, "duty_pct": None}
    if phase is None or wave is None:
        return out
    w = np.asarray(wave, dtype=np.float64)
    if len(w) < 32 or vpp <= 4 or not np.all(np.isfinite(w)):
        return out
    lo, hi = float(np.percentile(w, 5)), float(np.percentile(w, 95))
    if hi - lo < 0.2 * vpp:
        return out
    l10, l90 = lo + 0.10 * (hi - lo), lo + 0.90 * (hi - lo)
    mid = 0.5 * (lo + hi)

    start = int(np.argmin(w))
    wr = np.r_[w[start:], w[:start], w[start]]
    pr = np.r_[phase[start:], phase[:start] + 1.0, phase[start] + 1.0]

    c10 = _crossing(wr, l10, True)
    c90 = _crossing(wr, l90, True)
    if c10 is not None and c90 is not None and c90 > c10:
        a, b = _phase_at(pr, c10), _phase_at(pr, c90)
        if b > a:
            out["rise_cycles"] = b - a

    cf10 = _crossing(wr, l90, False)
    cf90 = _crossing(wr, l10, False)
    if cf10 is not None and cf90 is not None and cf90 > cf10:
        a, b = _phase_at(pr, cf10), _phase_at(pr, cf90)
        if b > a:
            out["fall_cycles"] = b - a

    out["duty_pct"] = float(100.0 * np.mean(w >= mid))

    # 过冲：上升沿 90% 点之后、下降沿开始之前的最高点
    if c90 is not None:
        i0 = int(math.ceil(c90))
        i1 = int(math.ceil(cf10)) if cf10 is not None and cf10 > i0 else len(wr) - 1
        if i1 > i0 + 1:
            pk = float(np.max(wr[i0:i1]))
            out["overshoot_pct"] = float(100.0 * (pk - hi) / max(hi - lo, EPS))
    # 下冲：下降沿 90% 点之后的最低点
    if cf90 is not None:
        i0 = int(math.ceil(cf90))
        i1 = int(math.ceil(c10 + len(w))) if c10 is not None else len(wr) - 1
        i1 = min(max(i1, i0 + 2), len(wr) - 1)
        if i1 > i0 + 1:
            tr = float(np.min(wr[i0:i1]))
            out["undershoot_pct"] = float(100.0 * (lo - tr) / max(hi - lo, EPS))
    return out


# ---------------------------------------------------------------------------
# 频谱峰值
# ---------------------------------------------------------------------------
def spectral_peaks(mag, n, fs, max_peaks=5, rel=0.10):
    """返回 [(freq_hz, amp, bin)]，按幅度降序，最多 max_peaks 个。"""
    if mag is None or len(mag) < 4:
        return []
    m = np.asarray(mag, dtype=np.float64)
    th = rel * float(m.max()) if m.max() > 0 else 0.0
    cand = []
    for i in range(1, len(m) - 1):
        if m[i] >= m[i - 1] and m[i] > m[i + 1] and m[i] >= th:
            y0, y1, y2 = m[i - 1], m[i], m[i + 1]
            d = (y0 - 2 * y1 + y2)
            off = 0.5 * (y0 - y2) / d if abs(d) > 1e-12 else 0.0
            cand.append((float(m[i]), i + off))
    cand.sort(reverse=True)
    out = []
    for amp, b in cand[:max_peaks]:
        out.append((float(b * fs / n), float(amp), float(b)))
    return out


def envelope(x):
    """Hilbert 包络（频域法，比 scipy.signal.hilbert 省一次拷贝）"""
    x = to_float(x)
    n = len(x)
    X = np.fft.fft(x - x.mean())
    h = np.zeros(n)
    if n % 2 == 0:
        h[0] = h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[0] = 1.0
        h[1:(n + 1) // 2] = 2.0
    return np.abs(np.fft.ifft(X * h))


def harmonic_fit_seq(x, f0, fs, n_harm=8):
    """加窗 + 逐个谐波剥离的幅度估计（THD 专用）。

    ★★ 为什么不能直接用上面 joint harmonic_fit 的幅度算 THD：
      窗口里通常不是整数个周期，基波与各次谐波的正交性被破坏，
      强基波会"漏"进 2~8 次谐波。实测 K=5.37 的纯正弦，joint 拟合给出
      THD=20%（真值 0%）；方波给出 32%（真值 41%）。
      正确做法：Hann 加窗抑制泄漏 + 从强到弱逐个拟合并**从残差里减掉**，
      前一个强分量不再污染后一个弱分量。实测纯正弦 THD=0.00%，
      理想方波 THD=41.4%（1/3,1/5,1/7 次谐波的理论值）。

    返回 dict：amps（n_harm,）、thd_pct、resid
    """
    x = to_float(x)
    n = len(x)
    out = {"amps": np.zeros(n_harm), "thd_pct": None, "resid": x - x.mean()}
    if not np.isfinite(f0) or f0 <= 0 or f0 >= fs * 0.5:
        return out
    t = np.arange(n, dtype=np.float64) / float(fs)
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / float(n))
    r = x - x.mean()
    amps = np.zeros(n_harm)
    for h in range(1, n_harm + 1):
        Ah = np.stack([np.cos(2.0 * np.pi * h * f0 * t),
                       np.sin(2.0 * np.pi * h * f0 * t)], axis=1)
        try:
            coef, *_ = np.linalg.lstsq(Ah * w[:, None], r * w, rcond=None)
        except np.linalg.LinAlgError:
            continue
        amps[h - 1] = float(math.hypot(coef[0], coef[1]))
        r = r - Ah @ coef
    out["amps"] = amps
    out["resid"] = r
    if amps[0] > EPS:
        out["thd_pct"] = float(100.0 * np.sqrt(np.sum(amps[1:] ** 2)) / amps[0])
    return out


def _debounce(times, gap):
    """按最小间隔去抖（保留第一个，之后距上一个不足 gap 的丢弃）"""
    if times is None or len(times) == 0:
        return np.asarray([], dtype=np.float64)
    keep = [float(times[0])]
    for t in times[1:]:
        if float(t) - keep[-1] >= gap:
            keep.append(float(t))
    return np.asarray(keep, dtype=np.float64)


def measure_edges(x, period, fs, level=None):
    """在**时域逐边沿**测量 10%~90% 上升/下降时间与过冲（不依赖折叠平均）。

    ★ 为什么不从折叠平均的周期波形上量：
      折叠要把 4096 点分到 512~2048 个相位箱里，每箱 1~2 个采样点；
      边沿只有 1~3 点宽，箱内平均 + 插值本身就会把边沿展宽约 1 个箱。
      而时域逐边沿测量直接在线性插值的穿越点上算，采样间隔 0.5 µs 时
      精度约 ±0.2 µs —— 这才是"1.2 µs 上升时间"该有的分辨率。

    返回 dict：rise_us / fall_us / overshoot_pct / undershoot_pct / n_edges
    """
    x = to_float(x)
    n = len(x)
    out = {"rise_us": None, "fall_us": None,
           "overshoot_pct": None, "undershoot_pct": None, "n_edges": 0}
    if not np.isfinite(period) or period < 8:
        return out
    if level is None:
        level = mid_level(x)
    vpp, lo, hi = robust_vpp(x)
    if vpp < 6 or hi - lo < 0.5 * vpp:
        return out
    l10, l90 = lo + 0.10 * (hi - lo), lo + 0.90 * (hi - lo)
    l90d, l10d = hi - 0.10 * (hi - lo), hi - 0.90 * (hi - lo)
    win = max(3, int(0.30 * period))

    up = _debounce(_crossings(x, level, True, _hyst_of(x)), 0.4 * period)
    rises, overs = [], []
    for c in up:
        i0 = max(0, int(math.floor(c)) - win)
        seg = x[i0:int(math.floor(c)) + 2]
        idx = np.where(seg <= l10)[0]
        if len(idx) == 0:
            continue
        i = i0 + int(idx[-1])
        if i + 1 >= n or x[i + 1] <= x[i]:
            continue
        t10 = i + (l10 - x[i]) / (x[i + 1] - x[i])
        j0 = int(math.ceil(c))
        seg2 = x[j0:min(n, j0 + win + 1)]
        idx2 = np.where(seg2 >= l90)[0]
        if len(idx2) == 0:
            continue
        j = j0 + int(idx2[0])
        if j <= 0 or x[j] <= x[j - 1]:
            continue
        t90 = j - (x[j] - l90) / (x[j] - x[j - 1])
        if t90 <= t10:
            continue
        rises.append((t90 - t10) / fs * 1e6)
        k0 = int(math.ceil(t90))
        seg3 = x[k0:min(n, k0 + win)]
        if len(seg3):
            overs.append(100.0 * (float(seg3.max()) - hi) / max(hi - lo, EPS))
    if rises:
        out["rise_us"] = float(np.median(rises))
        out["rise_us_std"] = float(np.std(rises))
        out["overshoot_pct"] = float(np.median(overs)) if overs else None

    dn = _debounce(_crossings(x, level, False, _hyst_of(x)), 0.4 * period)
    falls, unders = [], []
    for c in dn:
        i0 = max(0, int(math.floor(c)) - win)
        seg = x[i0:int(math.floor(c)) + 2]
        idx = np.where(seg >= l90d)[0]
        if len(idx) == 0:
            continue
        i = i0 + int(idx[-1])
        if i + 1 >= n or x[i] <= x[i + 1]:
            continue
        t90 = i + (x[i] - l90d) / (x[i] - x[i + 1])
        j0 = int(math.ceil(c))
        seg2 = x[j0:min(n, j0 + win + 1)]
        idx2 = np.where(seg2 <= l10d)[0]
        if len(idx2) == 0:
            continue
        j = j0 + int(idx2[0])
        if j <= 0 or x[j] >= x[j - 1]:
            continue
        t10 = j - (l10d - x[j]) / (x[j - 1] - x[j])
        if t10 <= t90:
            continue
        falls.append((t10 - t90) / fs * 1e6)
        k0 = int(math.ceil(t10))
        seg3 = x[k0:min(n, k0 + win)]
        if len(seg3):
            unders.append(100.0 * (lo - float(seg3.min())) / max(hi - lo, EPS))
    if falls:
        out["fall_us"] = float(np.median(falls))
        out["fall_us_std"] = float(np.std(falls))
        out["undershoot_pct"] = float(np.median(unders)) if unders else None
    out["n_edges"] = int(len(up) + len(dn))
    return out


def kurtosis(x):
    x = to_float(x)
    s = x.std()
    if s <= EPS:
        return 0.0
    return float(np.mean(((x - x.mean()) / s) ** 4) - 3.0)


def skewness(x):
    x = to_float(x)
    s = x.std()
    if s <= EPS:
        return 0.0
    return float(np.mean(((x - x.mean()) / s) ** 3))
