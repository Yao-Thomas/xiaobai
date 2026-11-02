#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_processing.py —— 时基、测量、包络、校准（不含硬件、不含 UI）

按用户方案拆分：
    scope_dual.py        只负责硬件寄存器和完整帧读取
    scope_processing.py  测量、迟滞、包络、时基、校准   ← 本文件
    scope_model.py       通道/触发/采集/显示配置状态
    apps_scope_dual.py   UI 绘制与触摸事件
    scope_dual.c         快速包络、直方图、测量核心

硬件事实（3PA1030 双通道模块 @ 领航者 J4）
    ADC 采样率 fs = 20 MHz（scope_adc_clk 给 AD 的 20MHz，ODDR 输出）
    一帧 DEPTH = 4096 个采样点
    抽取倍率 D：每 D 个 20MHz 采样取 1 个写进 BRAM
    => 帧内相邻两点时间 = D / fs = D * 50 ns
    => 一帧时间 = 4096 * D * 50 ns

电压（10 位，模块前端 VO = VI/5 + 1，0..1023 对应 VI = -5V..+5V）
    V(lsb) = (lsb - 511.5) * 10.0 / 1023     每 LSB ≈ 9.775 mV
"""
import math

DEPTH = 4096
FS_HZ = 20.0e6                  # ADC 采样率
SAMPLE_MAX = 1023
MID = 511.5
V_FULL = 10.0                   # 名义输入范围 -5V..+5V（3PA1030: VO=VI/5+1）
# ★★ 两点电压标定结果（改硬件/改前级后按同样方法重标）
#   标定模型: V = (lsb - CAL_ZERO) * V_FULL / SAMPLE_MAX * CAL_GAIN
# ★ 恢复到【名义值】，作为干净起点。
#   之前填过 504.339 / 0.980389，但那是我拿"已经被 V_CAL=0.9384 改过的读数"
#   又算了一遍（等于误差乘两次），实测真实 4V 被显示成 4.19V。
#   正确做法：保持名义值，由 cal_scope.py 读【原始 ADC 码】做两点标定，
#   结果写进 scope_cal.json（不改代码、也不会叠加误差）。
CAL_ZERO = 511.5                # 零点（LSB）—— 名义值
CAL_GAIN = 1.0                  # 增益修正 —— 名义值

# ★ 标定文件：由 cal_scope.py 生成。存在则优先使用它（不用改代码）。
#   格式: {"ch0": {"zero": 504.3, "gain": 0.9804}, "ch1": {...}}
CAL_FILE = "/home/zynq/ui/scope_cal.json"


def _load_cal():
    import json
    import os
    try:
        if os.path.exists(CAL_FILE):
            with open(CAL_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


CAL = _load_cal()
# ★ 电压标定【不要】用全局乘除系数（试过 V_CAL=0.9384，按用户反馈是错的：
#   单一系数只能修增益，修不了零点偏移，导致小信号与大信号两头都不准）。
#   正确做法是用每通道的 (zero, gain) 两点标定：
#       V = (lsb - zero) * V_FULL / SAMPLE_MAX * gain * probe
#   见 ChannelCal.to_volt 与 sd_cal 工具。

# ============================================================
# 一、统一时基表（步骤4）
#     全系统只有这一张表；UI 不再自行维护 NS_PER_PT
# ============================================================
# 每格时间（秒），10 格 = 一屏
TIME_DIV = [
    50e-9, 100e-9, 200e-9, 500e-9,
    1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6,
    100e-6, 200e-6, 500e-6, 1e-3, 2e-3, 5e-3,
]


def fmt_time(t):
    a = abs(t)
    if a < 1e-9:
        return "0"
    if a < 1e-6:
        return "%.0fns" % (t * 1e9)
    if a < 1e-3:
        return "%.3gus" % (t * 1e6) if a < 10e-6 else "%.1fus" % (t * 1e6)
    return "%.3gms" % (t * 1e3)


def fmt_freq(f):
    if not f or f <= 0:
        return "--"
    if f >= 1e6:
        return "%.4gMHz" % (f / 1e6)
    if f >= 1e3:
        return "%.4gkHz" % (f / 1e3)
    return "%.4gHz" % f


def fmt_volt(v):
    if abs(v) < 1.0:
        return "%+.1fmV" % (v * 1000)
    return "%+.3fV" % v


class Timebase:
    """把「每格时间」换算成真实的抽取倍率与显示跨度。

    用户方案：
        窗口时间 = Time/div × 10
        D        = ceil(fs × 窗口时间 / 4096)          # 抽取倍率
        span     = round(fs × 窗口时间 / D)            # 该窗口内实际采样点数
        实际 Time/div = span × D / fs / 10             # ★ 横轴显示这个
    """

    def __init__(self, index=4):
        self.index = index
        self.set(index)

    def set(self, index):
        self.index = max(0, min(len(TIME_DIV) - 1, index))
        self.req_tdiv = TIME_DIV[self.index]
        window = self.req_tdiv * 10.0                 # 一屏要覆盖的时间
        target = FS_HZ * window / DEPTH               # 想要的总抽取比
        self.dec = max(1, min(65535, int(math.ceil(target))))
        self.span = int(round(FS_HZ * window / self.dec))
        if self.span < 2:
            self.span = 2
        # ★ 真实值（横轴必须显示这个）
        self.actual_tdiv = self.span * self.dec / FS_HZ / 10.0
        self.dt = self.dec / FS_HZ                    # 帧内相邻两点时间
        self.err = (abs(self.actual_tdiv - self.req_tdiv) / self.req_tdiv
                    if self.req_tdiv else 0.0)
        return self

    def dec_register(self):
        """硬件的抽取/V_DIV 寄存器值：TIMEBASES 表的 div*dec 组合。
        硬件把抽取实现为 div(每点时钟数) × dec(再抽)，这里统一按 dec 下发。"""
        return self.dec

    def label(self):
        return fmt_time(self.actual_tdiv)


# ============================================================
# 二、电压换算 + 每通道校准（步骤7）
# ============================================================
# ============================================================================
# ★★ Vpp 分段线性标定表（2026-10-10 用户实测，CH1）
#
#   用户给的数据（真实 Vpp -> 名义显示 Vpp）：
#       1.00 -> 1.01
#       4.00 -> 4.29
#       6.00 -> 6.46
#       7.00 -> 7.57
#
#   比值 1.010 / 1.073 / 1.077 / 1.081 不是常数 -> 【不是纯比例误差】，
#   所以不能用"乘一个系数"修（试过 V_CAL，被用户否掉）。
#   用 (显示, 真实) 这些点做【分段线性插值】反解，等价于一条带截距的直线：
#       f(x) = 1.09333*x - 0.08333   (x=真实, f=显示)   最大偏差 0.25%
#   表的形式更通用：以后多测几个点直接加进去，不必改算法。
#
#   注意：这些是 Vpp（峰峰值），所以标的是【幅度刻度】。
#         Vmax/Vmin 由 中点 ± Vpp/2 推出，保证三者自洽。
# ============================================================================
VPP_CAL = [
    (0.00, 0.00),
    (1.01, 1.00),
    (4.29, 4.00),
    (6.46, 6.00),
    (7.57, 7.00),
]


def vpp_correct(v):
    """把名义 Vpp 校正成真实 Vpp（分段线性，超出表尾按末段斜率外推）"""
    if v is None:
        return None
    s = 1.0 if v >= 0 else -1.0
    x = abs(v)
    tab = VPP_CAL
    if x <= tab[0][0]:
        return v
    for i in range(1, len(tab)):
        x0, y0 = tab[i - 1]
        x1, y1 = tab[i]
        if x <= x1:
            if x1 <= x0:
                return s * y1
            return s * (y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    x0, y0 = tab[-2]
    x1, y1 = tab[-1]
    k = (y1 - y0) / (x1 - x0) if x1 > x0 else 1.0
    return s * (y1 + k * (x - x1))


class ChannelCal:
    """每通道：零点、增益、探头倍率、DC/数字AC 耦合"""


    def __init__(self, no=0):
        """no = 0/1，用于从标定文件里取【本通道】的 zero/gain。

        ★★ 电压标定必须用【两点】才能同时定出零点偏移和斜率：
              V = (lsb - zero) * V_FULL/SAMPLE_MAX * gain
           只用一个乘除系数（试过 V_CAL=0.9384）只能修斜率，
           结果是小信号被零点误差主导、大信号被斜率误差主导 —— 两头都不准。
           标定值由 cal_scope.py 两点标定后写进 scope_cal.json；
           文件不存在时用下面的内置默认值。
        """
        _c = CAL.get("ch%d" % no) or {}
        self.zero = float(_c.get("zero", CAL_ZERO))   # 零点（LSB）
        self.gain = float(_c.get("gain", CAL_GAIN))   # 增益修正
        self.probe = 1.0       # 探头倍率 x1 / x10
        self.ac = False        # 数字 AC 耦合（显示前减去均值）
        self.invert = False
        self.vdiv_idx = 5      # V/格索引（1V/div）
        self.vpos = 0.0        # 垂直位置（格）
        self.enabled = True

    def to_volt(self, lsb):
        v = (lsb - self.zero) * V_FULL / SAMPLE_MAX * self.gain
        if self.invert:
            v = -v
        return v * self.probe


# ============================================================
# 三、测量算法（步骤5）
#    1024 级直方图 -> 1%/99% 分位 -> 稳健 Vpp/中心 -> 迟滞边沿
#    -> 多周期取中位 -> 只统计完整周期的占空比
# ============================================================
def histogram(samples):
    h = [0] * 1024
    for v in samples:
        if 0 <= v <= 1023:
            h[v] += 1
    return h


def percentile_from_hist(h, n, frac):
    """从直方图求分位值（抗毛刺，比 min/max 稳健得多）"""
    if n <= 0:
        return 0
    want = int(n * frac)
    acc = 0
    for i, c in enumerate(h):
        acc += c
        if acc >= want:
            return i
    return 1023


def robust_limits(samples, lo_frac=0.01, hi_frac=0.99):
    """用 1%/99% 分位算稳健的最小/最大值（忽略孤立毛刺）"""
    h = histogram(samples)
    n = len(samples)
    lo = percentile_from_hist(h, n, lo_frac)
    hi = percentile_from_hist(h, n, hi_frac)
    return lo, hi, h


def hist_mean_rms(samples):
    n = len(samples)
    if n <= 0:
        return 0.0, 0.0
    s = 0.0
    s2 = 0.0
    for v in samples:
        s += v
        s2 += float(v) * v
    m = s / n
    var = s2 / n - m * m
    return m, (math.sqrt(var) if var > 0 else 0.0)


def median(xs):
    if not xs:
        return None
    a = sorted(xs)
    n = len(a)
    return a[n // 2] if n % 2 else 0.5 * (a[n // 2 - 1] + a[n // 2])


def trimmed_mean(xs, cut=0.2):
    """去极值平均：掐掉两端各 cut 比例再平均"""
    if not xs:
        return None
    a = sorted(xs)
    k = int(len(a) * cut)
    b = a[k:len(a) - k] if len(a) - 2 * k >= 1 else a
    return sum(b) / float(len(b))


def hysteresis_edges(samples, level, hys, rising=True, max_edges=200000):
    """迟滞（施密特）边沿检测 —— 与 PL 里那套逻辑一致，PS 侧复核一遍。

    上升沿：信号必须先 <= level-hys（武装），再 >= level+hys（触发）
    下降沿：信号必须先 >= level+hys（武装），再 <= level-hys（触发）
    中间那段（level±hys）是死区，噪声在里面来回摆不会产生假边沿。
    """
    if hys < 2:
        hys = 2
    hi = min(1023, level + hys)
    lo = max(0, level - hys)
    idx = []
    armed = False
    for i, v in enumerate(samples):
        if rising:
            if v <= lo:
                armed = True                     # 回到低侧 -> 武装
            elif v >= hi and armed:
                idx.append(i)                    # 穿过高侧 -> 触发
                armed = False
                if len(idx) >= max_edges:
                    break
        else:
            if v >= hi:
                armed = True                     # 回到高侧 -> 武装
            elif v <= lo and armed:
                idx.append(i)                    # 穿过低侧 -> 触发
                armed = False
                if len(idx) >= max_edges:
                    break
    return idx


def period_from_edges(idx):
    """从同类边沿序列估周期。返回 (周期点数, 用于平均的间隙列表) 或 (None, [])"""
    if len(idx) < 2:
        return None, []
    gaps = [idx[i + 1] - idx[i] for i in range(len(idx) - 1)]
    med = median(gaps)
    if not med or med <= 2:
        return None, gaps
    good = [g for g in gaps if 0.5 * med <= g <= 2.0 * med]
    if not good:
        return None, gaps
    per = trimmed_mean(good, 0.25) if len(good) >= 3 else median(good)
    return per, good


def measure(samples, dt, cal=None, hys=None):
    """完整测量。dt = 帧内相邻两点时间（秒）。

    返回 dict；信号太小或周期不稳定时 freq/period/duty 为 None，
    UI 应显示 "—" 而不是乱跳的数字。
    """
    n = len(samples)
    out = {"n": n, "locked": False}
    if n < 64:
        return out

    if cal is None:
        cal = ChannelCal()

    # ---- 数字 AC 耦合：先减去均值 ----
    data = samples
    if cal.ac:
        m0 = sum(samples) / float(n)
        data = [int(round(v - m0 + MID)) for v in samples]
        data = [min(1023, max(0, v)) for v in data]

    # ---- 稳健极值（1%/99% 分位）+ 原始极值 ----
    lo_p, hi_p, h = robust_limits(data)
    raw_min = min(data)
    raw_max = max(data)
    mean, rms = hist_mean_rms(data)

    pp = hi_p - lo_p
    center = (hi_p + lo_p) // 2

    out.update({
        "min": raw_min, "max": raw_max,
        "min_robust": lo_p, "max_robust": hi_p,
        "mid": center, "pp": pp, "pp_raw": raw_max - raw_min,
        "mean": mean, "rms": rms,
        # 电压
        "vpp": pp * V_FULL / SAMPLE_MAX * cal.gain * cal.probe,
        "vmax": cal.to_volt(hi_p),
        "vmin": cal.to_volt(lo_p),
        "vmean": cal.to_volt(mean),
        "vrms": rms * V_FULL / SAMPLE_MAX * cal.gain * cal.probe,
        "vpp_raw": (raw_max - raw_min) * V_FULL / SAMPLE_MAX * cal.gain * cal.probe,
    })

    # ---- 信号太小就不给频率（避免乱跳）----
    if pp < 24:      # ★ 噪声抑制：空闲时实测 pp 约 13 LSB
        out["note"] = "信号太小"
        return out

    # ---- 迟滞宽度：优先用传入值，否则按用户公式自动推导 ----
    if hys is None:
        hys = auto_hys(pp)
    hys = int(max(2, min(pp // 2, hys)))
    out["hys"] = hys

    # ---- 边沿 + 多周期平均 ----
    rises = hysteresis_edges(data, center, hys, rising=True)
    falls = hysteresis_edges(data, center, hys, rising=False)
    out["edges"] = len(rises)
    # ★ 只要 2 个边沿就能算出 1 个周期。
    #   验收基准 9.765625kHz = 20MHz/2048 -> 一帧 4096 点只有 2 个周期、
    #   1~2 个上升沿，所以这里【不能】要求 >=3 个边沿。
    # ---- 周期估计：优先同类边沿；不够就用「上升+下降」合并算半周期 ----
    per_pts = None
    good = []
    source = ""
    if len(rises) >= 2:
        per_pts, good = period_from_edges(rises)
        source = "上升沿"
    if per_pts is None and len(falls) >= 2:
        per_pts, good = period_from_edges(falls)
        source = "下降沿"
    if per_pts is None:
        # ★ 一帧里同类边沿不足（例如 9.765625kHz 只有 2 个周期、
        #   且以低半周结束 -> 只有 1 个上升沿），此时用所有跳变
        #   的间隔当【半周期】，再乘 2。
        allе = sorted(rises + falls)
        half, good2 = period_from_edges(allе)
        if half is not None:
            per_pts = half * 2.0
            good = [g * 2.0 for g in good2]
            source = "上升+下降(半周期x2)"

    if per_pts is not None:
        if True:
            if True:
                # 周期稳定性：相对散度
                med = median(good) if good else per_pts
                spread = ((max(good) - min(good)) / float(med)) if (good and med) else 0.0
                out["period_pts"] = per_pts
                out["period"] = per_pts * dt
                out["freq"] = 1.0 / out["period"] if out["period"] > 0 else None
                out["period_spread"] = spread
                out["period_src"] = source
                out["locked"] = spread < 0.25
                # ---- 占空比：只统计完整周期 ----
                # ---- 占空比：只统计完整周期的高电平时间 ----
                # 优先用「相邻上升沿之间按门限统计」，这样任意波形都对；
                # 一帧里上升沿不足 2 个时（验收基准就是这种 2 周期帧），
                # 退化成「上升沿 -> 其后第一个下降沿」的高电平宽度 / 周期。
                duty = None
                hi_thr = center + hys
                if len(rises) >= 2:
                    highs = 0
                    total = 0
                    for i in range(len(rises) - 1):
                        a, b = rises[i], rises[i + 1]
                        if b - a < 4:
                            continue
                        total += (b - a)
                        highs += sum(1 for v in data[a:b] if v >= hi_thr)
                    if total > 0:
                        duty = highs * 100.0 / total
                if duty is None and rises and falls and per_pts:
                    widths = []
                    for r in rises:
                        for f in falls:
                            if f > r:
                                widths.append(f - r)
                                break
                    if widths:
                        w = median(widths) if len(widths) < 3 else trimmed_mean(widths, 0.25)
                        if w and per_pts > 0:
                            duty = w * 100.0 / per_pts
                if duty is not None:
                    out["duty"] = duty

    if not out.get("freq"):
        out["note"] = "未锁定"
    return out


def auto_hys(pp):
    """用户公式：hys = max(噪声×3, Vpp/32, 2)。
    这里噪声没有单独估计，就用 Vpp/32 与 2 的下限；
    调用方若有噪声估计可用 noise*3 覆盖。"""
    return int(max(2, pp // 32))


# ============================================================
# 四、列包络（步骤5：半开区间 [a,e) + first/last/min/max）
# ============================================================
def envelope(samples, cols, offset=0):
    """把一帧采样压成 cols 列，每列返回 (first, last, min, max)。

    区间用【半开】[a, e)，相邻列不会重复采样点
    （原来写的 i <= e 会让两列共用边界点，放大后正弦显得发胖）。
    """
    n = len(samples)
    out = []
    if n <= 0 or cols <= 0:
        return out
    for x in range(cols):
        a = ((x + offset) * n) // cols
        e = ((x + offset + 1) * n) // cols
        if e <= a:
            e = a + 1
        a %= n
        e = ((e - 1) % n) + 1 if e > n else e
        seg = samples[a:e] if a < e else (samples[a:] + samples[:e])
        if not seg:
            out.append((0, 0, 0, 0))
            continue
        out.append((seg[0], seg[-1], min(seg), max(seg)))
    return out


def mixed_draw_columns(env, w):
    """混合绘制策略：
        span <= 屏幕宽  -> 点线连接（必要时插值），不做包络加粗
        span >  屏幕宽  -> 每列 min/max 包络 + 前一点到本点 first 的连线
    返回每列要画的竖线区间和连线端点。
    """
    out = []
    for i, (first, last, mn, mx) in enumerate(env[:w]):
        prev_last = env[i - 1][1] if i > 0 else first
        out.append({"col": i, "lo": mn, "hi": mx,
                    "link_from": prev_last, "link_to": first})
    return out
