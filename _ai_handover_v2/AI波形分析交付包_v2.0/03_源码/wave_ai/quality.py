"""
quality.py —— 波形质量评估（方向 2：端侧完全做不了、演示价值最高的能力）

输入：原始 4096 点（10 bit）+ 有效采样率 + 预测类别
输出：上升/下降时间、过冲/下冲、SNR、边沿抖动、THD、占空比稳定度、波形保真度、
      以及 0~100 综合质量评分

★★ 三条设计原则（决定了这些数字可不可信）

 1. **能从原始采样算的，绝不从图上估。**
    96×96 密度图里一列 = 42.7 个采样点；dec=10 时一列 = 21 µs。
    而典型上升时间是 1 µs 量级 —— 在图上只占 0.05 列，**根本看不见**。
    所以上升时间必须用"谐波最小二乘定基频 → 折叠平均一个周期 → 10%/90% 插值"来算。

 2. **算不出来的就报 null，不猜。**
    只有 2 个周期时无法定义"周期抖动"（至少要 2 个周期的间隔才有 1 个样本）；
    噪声/丢信号没有"质量"可言。这些情况一律返回 null + 原因，绝不拿一个假数字糊弄。

 3. **质量评分必须与波形类型相关。**
    方波的 THD 天然 43%（奇次谐波），用"THD 越低越好"去评分会得出"标准方波质量 0 分"
    的荒谬结论。所以失真项分成两支：
      · 正弦/三角/锯齿：用 THD（越低越好）
      · 方波/脉冲/阶跃：用**波形保真度**（与同占空比理想方波的相关系数）
    这是把"信号保真"与"波形固有谐波"分开的唯一正确做法。
"""
from __future__ import annotations

import math

import numpy as np

from . import dsp
from .config import LSB_TO_V, QUALITY_APPLICABLE

EPS = 1e-12

# 与波形类型相关的评分权重（缺项会自动归一化）
WEIGHTS = {
    "noise": 0.25,      # SNR
    "shape": 0.20,      # 波形保真度（非正弦类）
    "distortion": 0.15,  # THD（正弦/三角/锯齿）
    "overshoot": 0.12,
    "edge": 0.13,
    "stability": 0.15,
    "rail": 0.10,       # 撞轨/削顶
}

SQUARE_LIKE = {"square", "pulse", "step", "duty_abnormal", "clipping", "ringing", "glitch"}
SMOOTH_LIKE = {"sine", "triangle", "sawtooth"}
# 只有"电平跳变"类波形才谈上升/下降时间；正弦的 10%~90% 是半周期斜坡，不是边沿。
# ★ 毛刺(glitch)不算：它的折叠平均会被尖峰污染，测出来的"上升时间"是无意义的
#   （实测报出 97.9 µs），必须返回 null 而不是给个假数字。
EDGE_LABELS = {"square", "pulse", "step", "duty_abnormal", "ringing"}
# THD 只在"由谐波构成"的周期波形上有意义；毛刺/调频/双频的 THD 会被尖峰或边带放大
# （实测 glitch 的 THD 报到 169%），同样返回 null。
THD_LABELS = {"sine", "triangle", "sawtooth", "square", "duty_abnormal",
              "pulse", "clipping"}


def _clip01(v):
    return float(np.clip(v, 0.0, 1.0))


def _score_snr(snr_db):
    """15 dB → 0 分；40 dB → 100 分（10 bit + 13 LSB 噪声的典型工况约 25~30 dB）"""
    if snr_db is None:
        return None
    return 100.0 * _clip01((snr_db - 15.0) / 25.0)


def _score_overshoot(ov):
    if ov is None:
        return None
    return 100.0 * _clip01(1.0 - max(0.0, ov) / 20.0)


def _score_rail(clip_frac):
    if clip_frac is None:
        return None
    return 100.0 * _clip01(1.0 - clip_frac / 0.02)


def _score_edge(rise_us, fall_us, period_us):
    """边沿占周期的比例：<1% 满分，>15% 零分（方波类）"""
    vals = [v for v in (rise_us, fall_us) if v is not None]
    if not vals or not period_us:
        return None
    r = max(vals) / max(period_us, EPS)
    return 100.0 * _clip01(1.0 - (r - 0.01) / 0.14)


def _score_stability(jitter_ns, period_ns, duty_std_pct):
    """抖动相对周期 <0.2% 且占空比稳定度 <0.5% → 满分"""
    parts = []
    if jitter_ns is not None and period_ns:
        parts.append(_clip01(1.0 - (jitter_ns / period_ns) / 0.01))
    if duty_std_pct is not None:
        parts.append(_clip01(1.0 - duty_std_pct / 2.0))
    if not parts:
        return None
    return 100.0 * float(np.mean(parts))


def _score_distortion(thd_pct):
    if thd_pct is None:
        return None
    return 100.0 * _clip01(1.0 - thd_pct / 12.0)


# ---------------------------------------------------------------------------
# 波形保真度（方波/脉冲/阶跃类用）
# ---------------------------------------------------------------------------
def _template(kind, phase, duty):
    p = np.mod(phase, 1.0)
    if kind == "square":
        return np.where(p < duty, 1.0, -1.0)
    if kind == "sine":
        return np.sin(2.0 * np.pi * p)
    if kind == "triangle":
        d = np.clip(duty, 1e-3, 1 - 1e-3)
        return np.where(p < d, -1.0 + 2.0 * p / d, 1.0 - 2.0 * (p - d) / (1.0 - d))
    if kind == "sawtooth":
        return 2.0 * p - 1.0
    return None


def _fit_scale_offset(wave, tpl):
    a = np.stack([tpl, np.ones_like(tpl)], axis=1)
    coef, *_ = np.linalg.lstsq(a, wave, rcond=None)
    fit = a @ coef
    resid = wave - fit
    ss = float(np.var(resid))
    tot = float(np.var(wave))
    return 1.0 - ss / max(tot, EPS), fit


def shape_fidelity(phase, wave, kind, duty):
    """与"同类理想波形"的最大拟合优度 R²（允许相位/幅度/偏置）

    ★ 这是方波类唯一合理的"失真"度量：THD 对方波没有意义（它本来就由谐波构成）。
    ★ 用 FFT 循环互相关一次性枚举所有相位平移（比 192 次 lstsq 快 100 倍）：
      对 y = a·t + b 的最小二乘，R² 恒等于 corr(t,y)²，所以直接取最大相关即可。
    """
    tpl0 = _template(kind, phase, duty)
    if tpl0 is None or wave is None or len(wave) < 32:
        return None
    t = np.asarray(tpl0, dtype=np.float64)
    y = np.asarray(wave, dtype=np.float64)
    t = t - t.mean()
    y = y - y.mean()
    den = math.sqrt(float(np.dot(t, t)) * float(np.dot(y, y)))
    if den <= EPS:
        return None
    cc = np.fft.irfft(np.fft.rfft(y) * np.conj(np.fft.rfft(t)), len(t))
    return float(np.clip((float(cc.max()) / den) ** 2, 0.0, 1.0))


# ---------------------------------------------------------------------------
# 边沿时间序列（抖动 / 占空比稳定度）
# ---------------------------------------------------------------------------
def _crossings(x, level, rising=True):
    s = (x >= level).astype(np.int8)
    d = np.diff(s)
    idx = np.where(d == (1 if rising else -1))[0]
    out = []
    for i in idx:
        a, b = x[i], x[i + 1]
        if rising and b != a:
            out.append(i + (level - a) / (b - a))
        elif (not rising) and b != a:
            out.append(i + (a - level) / (a - b))
    return np.asarray(out, dtype=np.float64)


def period_stats(x, period, fs, level):
    """逐周期抖动与占空比稳定度（至少 4 个周期才算得出来）"""
    out = {"jitter_ns": None, "duty_std_pct": None, "n_periods": 0,
           "duty_mean_pct": None}
    if not np.isfinite(period) or period < 4:
        return out
    up = dsp._debounce(dsp._crossings(x, level, True, dsp._hyst_of(x)), 0.4 * period)
    dn = dsp._debounce(dsp._crossings(x, level, False, dsp._hyst_of(x)), 0.4 * period)
    n_per = int(np.floor(len(x) / period))
    out["n_periods"] = n_per
    if len(up) >= 4:
        t = np.diff(up)
        # 剔除异常间隔（漏检/毛刺）
        med = float(np.median(t))
        t = t[np.abs(t - med) < 0.25 * med]
        if len(t) >= 3:
            out["jitter_ns"] = float(np.std(t - np.mean(t)) / fs * 1e9)
    if len(up) >= 3 and len(dn) >= 3:
        duties = []
        for u in up:
            after = dn[dn > u]
            if len(after) == 0:
                continue
            d = (after[0] - u) / period
            if 0.0 < d < 1.0:
                duties.append(d)
        if len(duties) >= 3:
            out["duty_std_pct"] = float(np.std(duties) * 100.0)
            out["duty_mean_pct"] = float(np.mean(duties) * 100.0)
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def analyze_quality(raw, dec=10, fs_base=20e6, label=None, n_harm=8):
    """返回契约 §3.1 的 quality 字段（不可测项为 None）+ 评分依据"""
    x = np.asarray(raw, dtype=np.float64)
    n = len(x)
    fs = float(fs_base) / max(float(dec), 1e-9)
    vpp, lo, hi = dsp.robust_vpp(x)
    center = 511.5

    q = {
        "score": None,
        "applicable": bool(QUALITY_APPLICABLE.get(label, True)) if label else True,
        "rise_us": None, "fall_us": None,
        "overshoot_pct": None, "undershoot_pct": None,
        "snr_db": None, "jitter_ns": None, "thd_pct": None,
        "duty_stability_pct": None,
        "shape_fidelity": None,
        "coverage": 0.0,
        "components": {},
        "notes": [],
        "measurable": {},
        "fs_eff_hz": fs,
        "dec": int(dec),
        "vpp_v": float(vpp * LSB_TO_V),
        "offset_v": float((float(x.mean()) - center) * LSB_TO_V),
    }
    if vpp < 6:
        q["notes"].append("幅度过小，无法评估质量")
        q["applicable"] = False
        return q

    # ---- 1) 周期：优先用过零点间隔（对非带限波形无偏），谱估计只作兜底 ----
    k_spec, f0_spec, r2_spec, _ = dsp.estimate_tonal(x, fs)
    expected = (n / k_spec) if (np.isfinite(k_spec) and k_spec > 0) else None
    period_e, n_int, cv = dsp.period_from_crossings(x, expected=expected)
    use_edge = bool(np.isfinite(period_e) and n_int >= 1 and cv < 0.15)
    f0, period, src = None, float("nan"), None
    if use_edge:
        period = float(period_e)
        f0 = fs / period
        src = "crossings"
    elif np.isfinite(f0_spec) and r2_spec > 0.30:
        f0 = float(f0_spec)
        period = fs / f0
        src = "spectrum"
    if f0:
        q["freq_hz"] = float(f0)
        q["period_cycles"] = float(n * f0 / fs)
        q["period_source"] = src
        q["period_intervals"] = int(n_int)
        q["period_cv"] = float(cv)
        q["fit_r2"] = float(r2_spec)
    else:
        q["fit_r2"] = float(r2_spec)

    # ---- 2) 谐波拟合 → THD（只对谐波型周期波形）----
    want_thd = (label in THD_LABELS) or (label is None)
    hfit = dsp.harmonic_fit_seq(x, f0, fs, n_harm) if (f0 and want_thd) else None
    if hfit is not None and hfit["thd_pct"] is not None:
        q["thd_pct"] = float(hfit["thd_pct"])
        q["harmonics"] = [float(a) for a in hfit["amps"]]

    # ---- 3) SNR：谱噪声底（避免方波边沿残差被误算成噪声）----
    q["snr_db"] = _snr_db(x, fs, f0)

    # ---- 4) 边沿/过冲（时域逐边沿）+ 折叠波形的形状保真度 ----
    phase, wave = dsp.fold_period(x, period, nbins=1024) if f0 else (None, None)
    mid = dsp.mid_level(x)
    # ★ 占空比必须用"折叠后的一个周期"来算：
    #   整窗直接数"高于中值的比例"在非整数周期（真实工况 K≈2.04）下是有偏的：
    #   窗口从高电平中间开始，就会多数 8% —— 实测 50% 的方波被报成 58.7%。
    if wave is not None:
        q["duty_pct"] = float(100.0 * np.mean(wave >= mid))
    else:
        q["duty_pct"] = float(100.0 * np.mean(x >= mid))
    want_edge = (label in EDGE_LABELS) or (label is None)
    em = dsp.measure_edges(x, period, fs, mid) if (want_edge and f0) else {}
    if em.get("rise_us") is not None:
        q["rise_us"] = float(em["rise_us"])
        q["rise_us_std"] = float(em.get("rise_us_std") or 0.0)
    if em.get("fall_us") is not None:
        q["fall_us"] = float(em["fall_us"])
        q["fall_us_std"] = float(em.get("fall_us_std") or 0.0)
    if em.get("overshoot_pct") is not None:
        q["overshoot_pct"] = float(np.clip(em["overshoot_pct"], 0.0, 200.0))
    if em.get("undershoot_pct") is not None:
        q["undershoot_pct"] = float(np.clip(em["undershoot_pct"], 0.0, 200.0))
    q["n_edges_measured"] = int(em.get("n_edges") or 0)

    duty = float(np.clip(q["duty_pct"] / 100.0, 0.03, 0.97))
    if wave is not None and label in SQUARE_LIKE:
        q["shape_fidelity"] = shape_fidelity(phase, wave, "square", duty)
    elif wave is not None and label in SMOOTH_LIKE:
        q["shape_fidelity"] = shape_fidelity(phase, wave, label, duty)

    # ---- 5) 抖动 / 占空比稳定度 ----
    if f0:
        ps = period_stats(x, period, fs, dsp.mid_level(x))
        q["jitter_ns"] = ps["jitter_ns"]
        q["duty_stability_pct"] = ps["duty_std_pct"]
        q["n_periods"] = ps["n_periods"]

    # ---- 6) 撞轨 / 削顶 ----
    q["rail_frac"] = float(np.mean((x <= 2) | (x >= 1021)))
    q["flat_frac"] = float(_flat_fraction(x))

    # ---- 7) 评分 ----
    comp = {}
    period_us = (period / fs * 1e6) if (f0 and np.isfinite(period)) else None
    if q["applicable"]:
        comp["noise"] = _score_snr(q["snr_db"])
        comp["overshoot"] = _score_overshoot(q["overshoot_pct"])
        comp["edge"] = _score_edge(q["rise_us"], q["fall_us"], period_us)
        comp["stability"] = _score_stability(q["jitter_ns"],
                                             (period / fs * 1e9) if f0 else None,
                                             q["duty_stability_pct"])
        comp["rail"] = _score_rail(q["rail_frac"])
        if q["shape_fidelity"] is not None:
            comp["shape"] = 100.0 * _clip01((q["shape_fidelity"] - 0.80) / 0.19)
        if q["thd_pct"] is not None and label in SMOOTH_LIKE:
            comp["distortion"] = _score_distortion(q["thd_pct"])
        comp = {k: v for k, v in comp.items() if v is not None}
        if comp:
            wsum = sum(WEIGHTS[k] for k in comp)
            q["score"] = int(round(sum(comp[k] * WEIGHTS[k] for k in comp) / wsum))
            q["coverage"] = round(float(wsum / sum(WEIGHTS.values())), 3)
            q["components"] = {k: round(float(v), 1) for k, v in comp.items()}

    q["measurable"] = {k: (q[k] is not None) for k in
                       ("rise_us", "fall_us", "overshoot_pct", "snr_db",
                        "jitter_ns", "thd_pct", "duty_stability_pct")}

    # ---- 8) 人话备注（文本层直接引用）----
    if not q["applicable"]:
        q["notes"].append("该类别不评估质量")
    else:
        if q["snr_db"] is not None and q["snr_db"] < 25:
            q["notes"].append("信噪比偏低")
        if q["overshoot_pct"] is not None and q["overshoot_pct"] > 8:
            q["notes"].append("过冲偏大")
        if q["rail_frac"] > 0.001:
            q["notes"].append("触及量程边界")
        if q["rise_us"] is not None and period_us and (q["rise_us"] / period_us) > 0.05:
            q["notes"].append("边沿偏缓")
        if q["thd_pct"] is not None and label in SMOOTH_LIKE and q["thd_pct"] > 5:
            q["notes"].append("谐波失真偏大")
        if q["shape_fidelity"] is not None and q["shape_fidelity"] < 0.95:
            q["notes"].append("波形保真度偏低")
    return q


def _snr_db(x, fs, f0):
    """谱噪声底估 SNR：取"明显高于所有谐波"的频段中位数作为噪声 PSD"""
    n = len(x)
    x = x - x.mean()
    var = float(np.var(x))
    if var <= EPS:
        return None
    nperseg = min(512, n)
    try:
        from scipy.signal import welch
        f, pxx = welch(x, fs=fs, nperseg=nperseg, noverlap=nperseg // 2,
                       detrend="constant", scaling="density")
    except Exception:
        return None
    nyq = fs / 2.0
    lo = max(3.0 * (f0 or 0.0), 0.30 * nyq)
    hi = 0.48 * nyq
    band = (f >= lo) & (f <= hi)
    if band.sum() < 4:
        band = (f >= 0.40 * nyq) & (f <= 0.49 * nyq)
    if band.sum() < 2:
        return None
    noise_psd = float(np.median(pxx[band]))
    noise_pow = noise_psd * nyq
    if noise_pow <= 0:
        return None
    return float(np.clip(10.0 * math.log10(var / noise_pow), 0.0, 80.0))


def _flat_fraction(x):
    d = np.abs(np.diff(x))
    b = (d < 0.75).astype(np.int8)
    p = np.r_[0, b, 0]
    dd = np.diff(p)
    st = np.where(dd == 1)[0]
    en = np.where(dd == -1)[0]
    if len(st) == 0:
        return 0.0
    lens = en - st
    return float(lens[lens >= 8].sum()) / float(len(x))


# ---------------------------------------------------------------------------
# 自检：用"已知带宽的阶跃"验证上升时间测量精度
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from scipy.signal import butter, sosfilt
    rng = np.random.default_rng(0)
    print("=== 上升时间测量精度（周期方波 vs 连续时间理论值）===")
    fs = 2e6
    n = 4096
    for bw in (0.30, 0.50, 0.80):
        # 连续时间（100 倍采样）下的 10~90% 上升时间 = 真值
        fs_hi = fs * 100
        sos_hi = butter(2, bw * fs / fs_hi, "low", output="sos")
        step = np.zeros(400000)
        step[100000:] = 1.0
        y = sosfilt(sos_hi, step)
        i10 = int(np.argmax(y >= 0.1))
        i90 = int(np.argmax(y >= 0.9))
        tr_true = (i90 - i10) / fs_hi * 1e6
        # 采样后的周期方波（K=4，50% 占空比）
        n1 = 4096
        t = np.arange(n1) * 4.0 / n1          # ★ 4 个周期
        w = np.where(np.mod(t, 1.0) < 0.5, 1.0, -1.0)
        x = 511.5 + 250.0 * w
        x = sosfilt(butter(2, bw, "low", output="sos"), x)
        x = np.clip(np.rint(x + rng.normal(0, 2.0, n1)), 0, 1023)
        q = analyze_quality(x, dec=10, label="square")
        print("  bw=%.1f  实测 %s µs / 真值 %.3f µs  误差 %s  (采样间隔 0.5 µs)"
              % (bw, "%.3f" % q["rise_us"] if q["rise_us"] else "-", tr_true,
                 "%+.3f" % (q["rise_us"] - tr_true) if q["rise_us"] else "-"))

    print("\n=== 各类别质量字段可测性 ===")
    from .hw_sim import synth
    for lab in ("square", "sine", "noise", "signal_loss", "glitch"):
        raw, par = synth(lab, 3, rng)
        q = analyze_quality(raw[0], dec=int(par["dec"][0]), label=lab)
        print("  %-12s score=%-4s snr=%-5s rise=%-7s thd=%-6s cov=%.2f notes=%s"
              % (lab, q["score"],
                 "%.1f" % q["snr_db"] if q["snr_db"] else "-",
                 "%.2f" % q["rise_us"] if q["rise_us"] else "-",
                 "%.1f" % q["thd_pct"] if q["thd_pct"] else "-",
                 q["coverage"], q["notes"]))
