"""
hw_sim.py —— 真实采集链路仿真器（10 bit / 20 MSPS / 抽取 / 模拟带宽 / 13 LSB 噪声）

=============================================================================
★ 为什么要有 v2 的仿真器，而不是复用 v1 的 dds_sim
   v1（ai_training/src/common/dds_sim.py）按**板载 DDS 8 位、20 MSPS、dec=1**
   建模，服务于 PL 加速器的 28×28 输入。
   v2 面对的是**真实 AD 模块 + 真实信号源**：
     · 10 bit（0~1023），量程 -5V~+5V，V = (lsb-512)*10/1024
     · 抽取 dec（演示工况 dec=10 → 有效 2 MSPS，4096 点 = 2.048 ms）
     · 前端模拟带宽限制（边沿被圆滑，不是理想阶跃）
     · 真实噪声 ~13 LSB rms、ADC 失调、增益误差、触发相位抖动
   ⇒ 这些正是交接文档说的"仿真里没有、真实数据里有"的东西。
      不建模它们，训出来的模型到板子上必掉点。

★ 关键设计
   1. 以【窗口内周期数 K】为自变量而不是频率：K = f*4096/fs_eff。
      真实演示工况 f≈1 kHz、dec=10 ⇒ K≈2（和交接文档的 998.5 Hz 例子一致）。
      所以训练集必须重点覆盖 K∈[1.5,8]，而不是 v1 的 [4,64]。
   2. 每个类别都做**域随机化**（幅度/偏置/噪声/带宽/相位/增益），
      不靠数据增强"造"样本，而是让仿真本身覆盖硬件离散性。
   3. 保留 `hard` 域（更强噪声、更窄带宽、更大增益误差）**只用于测试**，
      用来估计"换一块板子/换一个信号源"时的掉点幅度（域偏移鲁棒性）。
   4. 毛刺/窄脉冲/阶跃用**分段函数**精确合成（不是近似），
      保证残差通道（representation ch2）拿到的是真实窄事件。

★ 输出
   raw : uint16 (n, 4096)，0~1023（与采集工具 JSONL 的 samples 完全同格式）
   par : dict[str, np.ndarray]，每个 (n,)，质量评估的真值（f0/rise/…）与溯源信息
=============================================================================
"""
from __future__ import annotations

import math

import numpy as np

from .config import (ADC_CENTER, ADC_MAX, CAP_LEN, CLASSES, FS_BASE)

# ---------------------------------------------------------------------------
# 域随机化参数
# ---------------------------------------------------------------------------
DOMAINS = {
    # 训练域：覆盖真实板卡的离散性
    # ★ 前端带宽：以 fs_eff/2 为 Nyquist，取 0.45~0.90（≈ 0.22~0.45·fs_eff）。
    #   这也是"上升时间"的来源：dec=10 时约 0.6~1.5 µs，与交接文档给的
    #   实测例子（rise_us=1.2）同量级。带宽再窄就会把 2~12 点的毛刺整个抹掉
    #   （实测 250 kHz 前端下毛刺残差只剩 0.2×vpp，与噪声底不可分）。
    "train": dict(noise=(7.0, 18.0), gain=(0.92, 1.08), bw=(0.45, 0.90),
                  dc=28.0, drift=3.0, small_amp_p=0.15),
    # 困难域（只用于测试）：更差信噪比 + 更窄带宽 + 更大增益误差
    "hard": dict(noise=(16.0, 32.0), gain=(0.80, 1.20), bw=(0.30, 0.55),
                 dc=45.0, drift=6.0, small_amp_p=0.25),
    # 干净域（用于质量评估算法的精度校验，避免噪声干扰测量本身）
    "clean": dict(noise=(1.5, 4.0), gain=(0.98, 1.02), bw=(0.80, 0.95),
                  dc=8.0, drift=1.0, small_amp_p=0.0),
}

# K 的覆盖：65% 集中在 [1.5, 8]（真实演示工况），其余到 32
K_RANGE = (1.5, 32.0)
K_FOCUS = (1.5, 8.0)
K_FOCUS_P = 0.65


def _u(rng, lo, hi, n):
    return rng.uniform(lo, hi, n)


def _logu(rng, lo, hi, n):
    return np.exp(rng.uniform(math.log(lo), math.log(hi), n))


def _pick(rng, seq, n):
    return np.asarray(seq)[rng.integers(0, len(seq), n)]


def _k(rng, n, lo=K_RANGE[0], hi=K_RANGE[1], focus_p=K_FOCUS_P):
    """周期数 K：混合分布（焦点区间 + 全范围），对准真实工况"""
    k = np.empty(n, dtype=np.float64)
    m = rng.random(n) < focus_p
    k[m] = _logu(rng, max(lo, K_FOCUS[0]), min(hi, K_FOCUS[1]), int(m.sum()))
    k[~m] = _logu(rng, lo, hi, int((~m).sum()))
    return k


def _normalize_p2p(w):
    """按每帧峰峰值归一到 2（让 vpp 由 half_amp 唯一决定）"""
    mn = w.min(axis=1, keepdims=True)
    mx = w.max(axis=1, keepdims=True)
    span = np.maximum(mx - mn, 1e-9)
    return 2.0 * (w - 0.5 * (mx + mn)) / span


def _normalize_peak(w):
    """按每帧 99.5 分位绝对值归一（对孤立尖峰稳健，用于正常波形）"""
    a = np.abs(w)
    q = np.percentile(a, 99.5, axis=1, keepdims=True)
    return w / np.maximum(q, 1e-9)


# ---------------------------------------------------------------------------
# 各波形族的合成（全部向量化；t 为 (1,4096)）
# ---------------------------------------------------------------------------
def _base_osc(rng, kind, t, n, k, ph0):
    """正弦/方波/三角/锯齿：返回 (w, duty)。ph0 为每帧初相（触发相位随机化）。

    ★ 相位必须在这里加，不能事后 np.roll：
      roll 的接缝对"窗口内非整数个周期"的信号是一个真实跳变，
      滤波后会在随机位置生成一根假边沿（实测 40 条方波里 30 条带假边沿）。
    """
    ph = k[:, None] * t + ph0[:, None]
    if kind == "sine":
        return np.sin(2.0 * np.pi * ph), np.full(n, 0.5)
    if kind == "square":
        duty = _u(rng, 0.48, 0.52, n)
        return np.where(np.mod(ph, 1.0) < duty[:, None], 1.0, -1.0), duty
    if kind == "triangle":
        duty = _u(rng, 0.46, 0.54, n)
        p = np.mod(ph, 1.0)
        d = duty[:, None]
        up = p / np.maximum(d, 1e-3)
        dn = (p - d) / np.maximum(1.0 - d, 1e-3)
        return np.where(p < d, -1.0 + 2.0 * up, 1.0 - 2.0 * dn), duty
    if kind == "sawtooth":
        p = np.mod(ph, 1.0)
        return 2.0 * p - 1.0, np.ones(n)
    raise ValueError(kind)


def _synth_simple(rng, label, t, n, ph0):
    """sine / square / triangle / sawtooth / duty_abnormal"""
    base = "square" if label == "duty_abnormal" else label
    k = _k(rng, n, 2.0 if label == "duty_abnormal" else K_RANGE[0], K_RANGE[1])
    w, duty = _base_osc(rng, base, t, n, k, ph0)
    if label == "duty_abnormal":
        light = rng.random(n) < 0.15
        duty = np.where(light,
                        np.where(rng.random(n) < 0.5,
                                 _u(rng, 0.42, 0.465, n), _u(rng, 0.535, 0.58, n)),
                        np.where(rng.random(n) < 0.5,
                                 _u(rng, 0.22, 0.42, n), _u(rng, 0.58, 0.78, n)))
        w = np.where(np.mod(k[:, None] * t + ph0[:, None], 1.0) < duty[:, None],
                     1.0, -1.0)
    return _normalize_peak(w), dict(k=k, duty=duty)


def _synth_noise(rng, t, n, ph0):
    sigma = _logu(rng, 6.0, 260.0, n)
    white = rng.normal(0.0, 1.0, (n, CAP_LEN))
    w = white
    # 40% 混入窄带干扰（电源/串扰），10% 混入 1/f 漂移
    m = rng.random(n) < 0.40
    if m.any():
        kk = _u(rng, 3.0, 200.0, n)[m]
        aa = _u(rng, 0.05, 0.35, n)[m]
        w[m] += (aa[:, None] * np.sin(2.0 * np.pi * kk[:, None] * t
                                       + _u(rng, 0, 6.28, n)[m][:, None]))
    m = rng.random(n) < 0.10
    if m.any():
        low = rng.normal(0.0, 1.0, (int(m.sum()), CAP_LEN)).cumsum(axis=1)
        low /= np.maximum(np.abs(low).max(axis=1, keepdims=True), 1e-9)
        w[m] += rng.uniform(0.3, 1.0, (int(m.sum()), 1)) * low
    w = w / np.maximum(np.abs(w).max(axis=1, keepdims=True), 1e-9)
    return w, dict(k=np.full(n, np.nan), sigma=sigma)


def _synth_clipping(rng, t, n, ph0):
    # ★ 削顶的底波形**不含方波**：方波本来就没有峰，把它"削"到 0.8 倍只是幅度变小，
    #   在增益随机的训练集里与干净方波**数据上不可分**（实测 clipping→square 误判 7/50）。
    #   削顶只在有峰值的波形上才有定义（正弦/三角/锯齿）。
    base = _pick(rng, ["sine", "triangle", "sawtooth"], n)
    k = _k(rng, n, 2.0, 24.0)
    w = np.zeros((n, CAP_LEN))
    for b in ("sine", "triangle", "sawtooth"):
        m = base == b
        if m.any():
            wb, _ = _base_osc(rng, b, t, int(m.sum()), k[m], ph0[m])
            w[m] = _normalize_peak(wb)
    lvl = np.where(rng.random(n) < 0.15, _u(rng, 0.85, 0.90, n), _u(rng, 0.45, 0.85, n))
    w = np.clip(w, -lvl[:, None], lvl[:, None])
    d = _u(rng, 0.44, 0.56, n)
    return w, dict(k=k, clip_level=lvl,
                   base_code=_pick(rng, [0, 2, 3], n), duty=d)


def _synth_signal_loss(rng, t, n, ph0):
    k = _k(rng, n, 2.0, 16.0)
    w = np.where(np.mod(k[:, None] * t + ph0[:, None], 1.0) < 0.5, 1.0, -1.0)
    flat = rng.random(n) < 0.18              # 整帧丢信号（纯平线）
    L = _u(rng, 0.08, 0.35, n)
    pos = rng.uniform(0.0, 1.0 - L)
    mode = rng.random(n) < 0.60              # drop / attenuate
    tt = t[0][None, :]
    seg = (tt >= pos[:, None]) & (tt < (pos + L)[:, None])
    w = np.where(flat[:, None], 0.0,
                 np.where(seg, np.where(mode[:, None], 0.0, w * 0.08), w))
    return w, dict(k=k, loss_len=L, flat=flat.astype(np.float64))


def _synth_pulse(rng, t, n, ph0):
    """孤立窄脉冲：1~3 个，宽度 1%~6% 窗口，其余为平直基线"""
    npulse = _pick(rng, [1, 1, 2, 2, 3], n)
    w = np.full((n, CAP_LEN), -0.5)
    tt = t[0][None, :]
    for j in range(3):
        act = npulse > j
        width = _u(rng, 0.010, 0.060, n)
        # 3 个脉冲的位置彼此错开（按 j 分段）
        pos = 0.06 + (j * 0.30) + rng.uniform(0.0, 0.22, n)
        pos = np.clip(pos, 0.0, 0.99 - width)
        seg = act[:, None] & (tt >= pos[:, None]) & (tt < (pos + width)[:, None])
        amp = _u(rng, 0.5, 1.0, n)
        w = np.where(seg, -0.5 + 2.0 * amp[:, None], w)
    return _normalize_p2p(w), dict(k=np.full(n, np.nan), n_pulse=npulse.astype(np.float64))


def _synth_step(rng, t, n, ph0):
    """单次电平跳变 + 可选一阶/二阶建立过冲"""
    tt = t[0][None, :]
    pos = rng.uniform(0.18, 0.78, n)
    up = rng.random(n) < 0.5
    lo, hi = -0.5, 0.5
    w = np.where((tt >= pos[:, None]) == up[:, None], hi, lo)
    # 阶跃后的建立过程（过冲 + 阻尼振荡，模拟真实边沿）
    u = np.where(tt >= pos[:, None], (tt - pos[:, None]) / 0.15, -1.0)
    settle = np.where(u >= 0,
                      0.10 * np.exp(-np.maximum(u, 0) * 6.0) *
                      np.sin(2.0 * np.pi * 14.0 * np.maximum(u, 0)), 0.0)
    w = w + settle * np.where(up[:, None], 1.0, -1.0)
    return _normalize_p2p(w), dict(k=np.full(n, np.nan), step_pos=pos,
                                   step_up=up.astype(np.float64))


def _synth_am(rng, t, n, ph0):
    """幅度调制：载波 Kc∈[8,48]，包络 Km∈[1,3] 个周期（与 hum 的低频漂移严格分开）"""
    kc = _k(rng, n, 8.0, 48.0)
    km = _u(rng, 1.0, 3.0, n)
    m = _u(rng, 0.25, 0.80, n)
    ph = _u(rng, 0, 2 * np.pi, n)
    env = 1.0 + m[:, None] * np.sin(2.0 * np.pi * km[:, None] * t + ph[:, None])
    carrier = rng.random(n) < 0.5
    s = np.sin(2.0 * np.pi * (kc[:, None] * t + ph0[:, None]))
    sq = np.sign(s)
    car = np.where(carrier[:, None], sq, s)
    w = env * car
    return _normalize_peak(w), dict(k=kc, mod_index=m, mod_freq=km,
                                    base_code=carrier.astype(np.float64))


def _synth_fm(rng, t, n, ph0):
    kc = _k(rng, n, 8.0, 48.0)
    km = _u(rng, 1.0, 3.0, n)
    beta = _u(rng, 0.8, 6.0, n)
    ph = _u(rng, 0, 2 * np.pi, n)
    phase = 2.0 * np.pi * (kc[:, None] * t + ph0[:, None]) + beta[:, None] * np.sin(
        2.0 * np.pi * km[:, None] * t + ph[:, None])
    return np.sin(phase), dict(k=kc, mod_index=beta, mod_freq=km)


def _synth_ringing(rng, t, n, ph0):
    # ★ 振铃频率必须落在"图上看得见"的区间：
    #   96 列 / 4096 点 ⇒ 每列 42.7 点；K_r=30 时 3.2 列/周期（勉强可见），
    #   K_r=50 时 1.9 列/周期（已到图像 Nyquist，完全混叠成噪声）。
    #   同理衰减常数太小（0.03 周期）时振铃只占 1 列，与"边沿噪声"不可分。
    k = _k(rng, n, 2.0, 8.0)
    duty = _u(rng, 0.44, 0.56, n)
    p = np.mod(k[:, None] * t + ph0[:, None], 1.0)
    car = np.where(p < duty[:, None], 1.0, -1.0)
    kr = _u(rng, 8.0, 30.0, n)
    tau = _u(rng, 0.06, 0.25, n)
    # 距最近一次跳变的周期数
    u = np.minimum(np.mod(p, 1.0), np.mod(p - duty[:, None], 1.0))
    ring = np.exp(-u / tau[:, None]) * np.sin(2.0 * np.pi * kr[:, None] * u)
    w = car + _u(rng, 0.18, 0.60, n)[:, None] * ring
    burst = rng.random(n) < 0.35
    if burst.any():
        m = int(burst.sum())
        start = _u(rng, 0.1, 0.5, m)
        bb = _u(rng, 0.25, 0.8, m)
        uu = t[0][None, :] - start[:, None]
        base = np.where(uu >= 0, bb[:, None] * np.exp(-uu / _u(rng, 0.08, 0.3, m)[:, None])
                        * np.sin(2.0 * np.pi * _u(rng, 8, 28, m)[:, None] * uu), 0.0)
        w[burst] = base
    return _normalize_peak(w), dict(k=k, duty=duty, ring_freq=kr, ring_tau=tau,
                                    burst=burst.astype(np.float64))


def _synth_double_freq(rng, t, n, ph0):
    k1 = _k(rng, n, 2.0, 16.0)
    ratio = _pick(rng, [1.35, 1.5, 1.7, 2.0, 2.5, 3.0, 3.5], n)
    k2 = k1 * ratio
    a = _u(rng, 0.35, 1.0, n)
    ph1 = _u(rng, 0, 2 * np.pi, n)
    ph2 = _u(rng, 0, 2 * np.pi, n)
    w = (np.sin(2.0 * np.pi * k1[:, None] * t + ph1[:, None])
         + a[:, None] * np.sin(2.0 * np.pi * k2[:, None] * t + ph2[:, None]))
    return _normalize_peak(w), dict(k=k1, ratio=ratio, amp2=a)


def _synth_hum(rng, t, n, ph0):
    """工频干扰：≤0.3 个周期的极低频漂移（与 am 的 ≥1 个包络周期区分）

    ★ 幅度必须够大：0.08 倍幅度的 50 Hz 漂移在 2 ms 窗口里与"干净正弦 + 直流偏置"
      肉眼看不出差别（实测 hum→sine 误判 6/50，属于标签噪声）。
      取 0.18~0.55 倍，并把"纯工频"比例提到 25%，让该类有明确定义。
    """
    kh = _u(rng, 0.06, 0.30, n)
    ah = _u(rng, 0.18, 0.55, n)
    ph = _u(rng, 0, 2 * np.pi, n)
    hum = ah[:, None] * np.sin(2.0 * np.pi * kh[:, None] * t + ph[:, None])
    pure = rng.random(n) < 0.25
    base = _pick(rng, ["sine", "square", "triangle"], n)
    k = _k(rng, n, 2.0, 16.0)
    w = np.zeros((n, CAP_LEN))
    for b in ("sine", "square", "triangle"):
        m = (base == b) & (~pure)
        if m.any():
            wb, _ = _base_osc(rng, b, t, int(m.sum()), k[m], ph0[m])
            w[m] = _normalize_peak(wb)
    w = w + hum
    return _normalize_peak(w), dict(k=k, hum_amp=ah, hum_freq=kh,
                                    base_code=_pick(rng, [0, 1, 2, 3], n))


def _synth_glitch(rng, t, n, ph0):
    """正常波形 + 1~3 个 2~12 采样点宽的尖峰（用三角脉冲精确合成）

    ★ 底波形只用正弦/方波：三角波的峰本身就是尖的，叠一个小毛刺后
      与原三角波不可分（标签噪声）。毛刺幅度下限取 1.0 倍幅度，保证"看得见"。
    """
    base = _pick(rng, ["sine", "sine", "square"], n)
    k = _k(rng, n, 2.0, 8.0)
    w = np.zeros((n, CAP_LEN))
    for b in ("sine", "square"):
        m = base == b
        if m.any():
            wb, _ = _base_osc(rng, b, t, int(m.sum()), k[m], ph0[m])
            w[m] = _normalize_peak(wb)
    npts = t.shape[1]
    idx = np.arange(npts)[None, :]
    count = _pick(rng, [1, 1, 1, 2, 2, 3], n)
    for j in range(3):
        act = count > j
        pos = rng.integers(64, npts - 64, n).astype(np.float64)
        width = _pick(rng, [2, 2, 3, 5, 8, 12], n).astype(np.float64)
        mag = _u(rng, 1.0, 2.8, n) * _pick(rng, [-1.0, 1.0], n)
        tri = np.clip(1.0 - np.abs(idx - pos[:, None]) / np.maximum(width[:, None], 1.0), 0.0, 1.0)
        w = w + np.where(act[:, None], mag[:, None] * tri, 0.0)
    return w, dict(k=k, n_glitch=count.astype(np.float64),
                   base_code=_pick(rng, [0, 1], n))


_SYNTH = {
    "sine": lambda rng, t, n, p: _synth_simple(rng, "sine", t, n, p),
    "square": lambda rng, t, n, p: _synth_simple(rng, "square", t, n, p),
    "triangle": lambda rng, t, n, p: _synth_simple(rng, "triangle", t, n, p),
    "sawtooth": lambda rng, t, n, p: _synth_simple(rng, "sawtooth", t, n, p),
    "duty_abnormal": lambda rng, t, n, p: _synth_simple(rng, "duty_abnormal", t, n, p),
    "noise": _synth_noise,
    "clipping": _synth_clipping,
    "signal_loss": _synth_signal_loss,
    "pulse": _synth_pulse,
    "step": _synth_step,
    "am": _synth_am,
    "fm": _synth_fm,
    "ringing": _synth_ringing,
    "double_freq": _synth_double_freq,
    "hum": _synth_hum,
    "glitch": _synth_glitch,
}


# ---------------------------------------------------------------------------
# 参数采样 + 主入口
# ---------------------------------------------------------------------------
def sample_params(rng, n, domain="train"):
    d = DOMAINS[domain]
    dec = _pick(rng, [10, 10, 10, 10, 5, 20, 1], n).astype(np.float64)
    fs_eff = FS_BASE / dec
    small = rng.random(n) < d["small_amp_p"]
    half_amp = np.where(small, _u(rng, 25.0, 140.0, n), _u(rng, 150.0, 470.0, n))
    return dict(
        dec=dec,
        fs_eff=fs_eff,
        half_amp=half_amp,
        gain=_u(rng, d["gain"][0], d["gain"][1], n),
        dc=_u(rng, -d["dc"], d["dc"], n),
        drift=_u(rng, 0.0, d["drift"], n),
        noise=_u(rng, d["noise"][0], d["noise"][1], n),
        bw=_u(rng, d["bw"][0], d["bw"][1], n),
        phase0=_u(rng, 0.0, 1.0, n),
    )


def synth(label: str, n: int, rng: np.random.Generator, domain: str = "train",
          chunk: int = 512):
    """生成 n 条指定类别的采集帧。返回 (raw uint16 (n,4096), par dict[str,array(n,)])"""
    from scipy.signal import butter, sosfilt

    assert label in CLASSES, label
    raw = np.empty((n, CAP_LEN), dtype=np.uint16)
    acc = {}
    t = (np.arange(CAP_LEN, dtype=np.float64) / float(CAP_LEN))[None, :]

    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        m = e - s
        P = sample_params(rng, m, domain)
        # ★ 相位（触发抖动）在合成时就加进去，不再事后 np.roll：
        #   roll 会在接缝处对"窗口内非整数周期"的信号制造真实跳变。
        w, extra = _SYNTH[label](rng, t, m, P["phase0"])
        w = np.asarray(w, dtype=np.float64)
        if w.shape != (m, CAP_LEN):
            raise RuntimeError("%s 合成形状错误: %s" % (label, w.shape))

        # 模拟链路：增益、直流、缓慢漂移
        tt = t[0][None, :]
        drift = P["drift"][:, None] * (tt - 0.5)
        y = ADC_CENTER + P["gain"][:, None] * P["half_amp"][:, None] * w \
            + P["dc"][:, None] + drift

        # 前端模拟带宽（2 阶低通，截止 = bw * fs_eff/2）
        #
        # ★★ 用"稳态初值"(zi) 初始化，而不是零状态：
        #   sosfilt 默认把历史当成 0（相当于输入一直是 0 码），
        #   滤波输出会从 0 猛冲到真实电平，在帧首制造一个巨大的假边沿。
        #   用 sosfilt_zi × 首采样值初始化 = 假设信号在采集前就已经是当前电平。
        p = 0.5 * P["bw"]
        for i in range(m):
            sos = butter(2, float(np.clip(p[i], 0.02, 0.98)), "low", output="sos")
            from scipy.signal import sosfilt_zi
            zi = sosfilt_zi(sos) * y[i, 0]
            y[i], _ = sosfilt(sos, y[i], zi=zi)

        # 真实噪声（10 bit 码值域）
        y = y + rng.normal(0.0, 1.0, y.shape) * P["noise"][:, None]

        # ADC 量化 + 限幅
        raw[s:e] = np.clip(np.rint(y), 0.0, float(ADC_MAX)).astype(np.uint16)

        par = dict(P)
        par.update(extra)
        for k, v in par.items():
            v = np.asarray(v, dtype=np.float64).reshape(m)
            acc.setdefault(k, []).append(v)

    out = {}
    for k, vs in acc.items():
        out[k] = np.concatenate(vs)
    out["vpp_lsb"] = 2.0 * out["half_amp"] * out["gain"]
    return raw, out


def synth_mixed(labels, per_class: int, rng, domain="train", chunk=512):
    """按类别均衡生成；真正逐类调用（每类参数分布独立）"""
    xs, ys = [], []
    for ci, lab in enumerate(labels):
        r, _ = synth(lab, per_class, rng, domain=domain, chunk=chunk)
        xs.append(r)
        ys.append(np.full(per_class, ci, dtype=np.int16))
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    idx = rng.permutation(len(x))
    return x[idx], y[idx]


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    print("=== hw_sim 自检 ===")
    for lab in CLASSES:
        r, p = synth(lab, 16, rng, domain="train", chunk=16)
        vpp = p["vpp_lsb"]
        print("%-14s vpp=%6.1f  K=%6.2f  dec=%4.0f  f0=%8.1fHz  uint16[%d,%d]"
              % (lab, float(np.median(vpp)), float(np.nanmedian(p["k"])),
                 float(np.median(p["dec"])),
                 float(np.nanmedian(p["k"] * p["fs_eff"] / CAP_LEN)),
                 int(r.min()), int(r.max())))
