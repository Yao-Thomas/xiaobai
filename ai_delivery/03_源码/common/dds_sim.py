"""
dds_sim.py —— 板载 DDS + 采集通路的位级仿真器（数据集生成器的"信号源"）

=============================================================================
★ 为什么需要它
   接口 ② 规定：数据由示波器负责人用板载 DDS 自动生成（DDS 参数即标签）。
   但数据生成不能阻塞模型训练，所以这里**按板卡的真实 DDS 语义**做一个仿真源：
     · scope IP 寄存器 FREQ： f = FREQ × 20MHz / 2^32   （09_板子与工具链.md §5）
     · 数据 8 位无符号 0~255，满量程中心 127.5
     · 抽取 DEC 1~255 → 实际采样率 fs = 20MHz / DEC
   ⇒ 仿真样本与真板采集**同格式、同量纲**，示波器负责人后续用真板数据
     只需重跑 preprocess（脚本已提供），模型无需改动。
   ★ 数据集 meta.json 里用 "source":"sim_dds" / "hw_scope" 明确区分，绝不含糊。

★ 关键设计：以【缓冲区内周期数 K】为自变量
   K = f × 4096 / fs。示波器"显示 2~5 个周期"对应 K=2~5；
   而 STFT 要看清谐波结构需要更多周期，故训练集主用 K ∈ [4, 64]（对数均匀）。
   考核/演示时另用 K=2~5 的真板工况做鲁棒性验证。
=============================================================================
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any

import numpy as np

CAP_LEN = 4096
FS_BASE = 20_000_000.0          # DIV 默认 5 → 20 MSPS
FULL_SCALE_CENTER = 127.5
AMP_MAX = 127.5

# 波形编号（与 scope IP SRC[2:1] 一致：0=正弦 1=方波 2=三角 3=锯齿）
WAVE_SINE, WAVE_SQUARE, WAVE_TRIANGLE, WAVE_SAWTOOTH = 0, 1, 2, 3
WAVE_NAMES = {WAVE_SINE: "sine", WAVE_SQUARE: "square",
              WAVE_TRIANGLE: "triangle", WAVE_SAWTOOTH: "sawtooth"}

# 9 类标签全集（★ 冻结顺序，禁止改动：模型输出索引 = 该列表下标）
CLASSES = ["sine", "square", "triangle", "sawtooth", "noise",
           "glitch", "clipping", "signal_loss", "duty_abnormal"]
ANOMALY_CLASSES = ["glitch", "clipping", "signal_loss", "duty_abnormal"]
CLEAN_CLASSES = ["sine", "square", "triangle", "sawtooth", "noise"]

# ---------------------------------------------------------------------------
# ★★ 关于 glitch（毛刺）的实测结论 —— 见 docs/01_输入表示选型.md §4
#
#   实测（scripts/_diag_glitch2.py）：一个 2~10 采样点的毛刺，落在 4096 点采集里
#   只占 146 点时间列的 1.4%~6.8%，映射到 28×28 密度图后
#   **只改变 2~5 个像素（共 784 个），且对比度很低**。
#   用同样的表示做"毛刺 vs 干净波形"二分类，模型只能收敛到多数类
#   （test_acc = 正例比例 = 0.80，毛刺召回 0.000）——
#   说明毛刺信息在这张 28×28 画布上**不可分**，不是模型或训练的问题。
#
#   这与团队分工本身是一致的：`06_分工总表_核对版.md` 里示波器负责人的第 3 项
#   就是 **PL 硬件级故障检测**，原文写着
#   "★ 毛刺是 ns 级的，CPU 采样根本采不到 —— 只有 FPGA 能在信号源头抓"，
#   用 100 MHz（10 ns 分辨率）在 PL 里做毛刺计数。
#
#   ⇒ 本项目默认交付 **8 类**（5 种波形 + 3 种"在 4096 点采集里看得见"的异常）。
#     需要 9 类时用 `--with-glitch` 重新生成数据集即可，代码路径完全一样。
# ---------------------------------------------------------------------------
CLASSES_NO_GLITCH = ["sine", "square", "triangle", "sawtooth", "noise",
                     "clipping", "signal_loss", "duty_abnormal"]
CLASSES_REQUIRING_PL = ["glitch"]      # 归 PL 硬件检测器负责的类别


def classes_for(with_glitch: bool = False):
    """训练/交付使用的类别表（顺序即模型输出下标）"""
    return list(CLASSES) if with_glitch else list(CLASSES_NO_GLITCH)


# ---------------------------------------------------------------------------
# 理想波形（相位 θ ∈ [0,1) 表示一个周期）
# ---------------------------------------------------------------------------
def wave_ideal(kind: int, phase: np.ndarray, duty: float = 0.5) -> np.ndarray:
    """返回 [-1, 1] 的理想波形，phase 为周期内的归一化相位（可为任意实数）"""
    p = np.mod(phase, 1.0)
    if kind == WAVE_SINE:
        return np.sin(2.0 * np.pi * p)
    if kind == WAVE_SQUARE:
        return np.where(p < duty, 1.0, -1.0)
    if kind == WAVE_TRIANGLE:
        # 上升沿 0->0.5，下降沿 0.5->1；duty 控制对称性（duty=0.5 为标准三角）
        d = max(1e-3, min(1.0 - 1e-3, duty))
        up = p / d
        dn = (p - d) / (1.0 - d)
        return np.where(p < d, -1.0 + 2.0 * up, 1.0 - 2.0 * dn)
    if kind == WAVE_SAWTOOTH:
        d = max(1e-3, min(1.0 - 1e-3, duty))
        return np.where(p < d, -1.0 + 2.0 * (p / d), -1.0)
    raise ValueError("unknown waveform %r" % kind)


def freq_word_from_hz(f_hz: float) -> int:
    """f = FREQ × 20MHz / 2^32 ⇒ FREQ = f × 2^32 / 20MHz（与板端寄存器一致）"""
    return int(round(f_hz * (2 ** 32) / FS_BASE)) & 0xFFFFFFFF


def hz_from_freq_word(word: int) -> float:
    return (word & 0xFFFFFFFF) * FS_BASE / (2 ** 32)


# ---------------------------------------------------------------------------
# 采集参数
# ---------------------------------------------------------------------------
@dataclass
class CaptureSpec:
    kind: int                       # 波形类型 WAVE_*
    cycles: float                   # 缓冲区内周期数 K
    amp: float                      # 幅度（0..127.5）
    duty: float = 0.5
    phase0: float = 0.0             # 初相（周期数）
    dc: float = 0.0                 # 直流偏置（LSB）
    gain: float = 1.0               # 通道增益误差
    noise_lsb: float = 1.0          # 高斯噪声标准差（LSB）
    jitter: float = 0.0             # 采样时钟抖动（周期数 rms）
    dec: int = 1                    # 抽取，决定 fs
    dither_uniform: float = 0.0     # 均匀量化抖动（LSB）
    anomaly: Optional[str] = None
    anomaly_params: Dict[str, Any] = field(default_factory=dict)

    @property
    def fs_hz(self) -> float:
        return FS_BASE / float(self.dec)

    @property
    def f_hz(self) -> float:
        return self.cycles * self.fs_hz / CAP_LEN


# ---------------------------------------------------------------------------
# 异常注入（★ 四种异常与任务书一致：毛刺/削顶/丢信号/占空比异常）
# ---------------------------------------------------------------------------
def _inject_glitch(y: np.ndarray, rng: np.random.Generator, amp: float) -> Dict[str, Any]:
    n = int(rng.integers(1, 4))
    info = {"n_glitch": n, "widths": [], "positions": []}
    for _ in range(n):
        w = int(rng.integers(2, 11))                      # 2~10 个采样点宽
        pos = int(rng.integers(64, CAP_LEN - 64 - w))
        sign = 1.0 if rng.random() < 0.5 else -1.0
        mag = sign * amp * float(rng.uniform(0.6, 2.6))
        y[pos:pos + w] += mag
        info["widths"].append(w)
        info["positions"].append(pos)
    return info


def _inject_clipping(y: np.ndarray, rng: np.random.Generator, amp: float) -> Dict[str, Any]:
    # ★ 刻意做"人眼不易察觉"的轻度~中度削顶：保留 55%~90% 峰值
    lvl = amp * float(rng.uniform(0.55, 0.90))
    y2 = np.clip(y, -lvl, lvl)
    frac = float(np.mean(np.abs(y) >= lvl - 1e-9))
    y[:] = y2
    return {"clip_level": float(lvl), "clip_frac": frac}


def _inject_signal_loss(y: np.ndarray, rng: np.random.Generator) -> Dict[str, Any]:
    # 两种表现：① 完全丢失（回到中位电平，平线）② 严重衰减（"信号很弱"）
    L = int(CAP_LEN * float(rng.uniform(0.08, 0.35)))
    pos = int(rng.integers(0, CAP_LEN - L + 1))
    mode = "drop" if rng.random() < 0.6 else "attenuate"
    if mode == "drop":
        y[pos:pos + L] = FULL_SCALE_CENTER
    else:
        y[pos:pos + L] = FULL_SCALE_CENTER + (y[pos:pos + L] - FULL_SCALE_CENTER) * 0.10
    return {"loss_mode": mode, "loss_len": L, "loss_pos": pos}


def _inject_duty(y: np.ndarray, rng: np.random.Generator) -> Dict[str, Any]:
    # duty 异常在参数层实现（见 build_capture）；此处仅记录
    return {}


# ---------------------------------------------------------------------------
# 生成一次采集
# ---------------------------------------------------------------------------
def build_capture(spec: CaptureSpec, rng: np.random.Generator, want_info: bool = False):
    """按参数生成 4096 个 8 位样本（uint8）。want_info=True 时额外返回异常注入细节。"""
    n = np.arange(CAP_LEN, dtype=np.float64)
    jit = rng.normal(0.0, spec.jitter, size=CAP_LEN) if spec.jitter > 0 else 0.0
    phase = spec.phase0 + (spec.cycles * (n + jit) / CAP_LEN)

    w = wave_ideal(spec.kind, phase, spec.duty)
    y = FULL_SCALE_CENTER + spec.dc + spec.gain * spec.amp * w

    info: Dict[str, Any] = {}
    if spec.anomaly == "glitch":
        info = _inject_glitch(y, rng, spec.amp)
    elif spec.anomaly == "clipping":
        info = _inject_clipping(y, rng, spec.amp)
    elif spec.anomaly == "signal_loss":
        info = _inject_signal_loss(y, rng)

    if spec.noise_lsb > 0:
        y = y + rng.normal(0.0, spec.noise_lsb, size=CAP_LEN)
    if spec.dither_uniform > 0:
        y = y + rng.uniform(-spec.dither_uniform, spec.dither_uniform, size=CAP_LEN)

    y = np.clip(np.rint(y), 0.0, 255.0).astype(np.uint8)
    if want_info:
        info["n_rail_samples"] = int(np.sum((y == 0) | (y == 255)))
        return y, info
    return y


def build_noise_capture(spec: CaptureSpec, rng: np.random.Generator) -> np.ndarray:
    """纯噪声类：无周期结构（可带带限/工频干扰）"""
    y = np.full(CAP_LEN, FULL_SCALE_CENTER + spec.dc, dtype=np.float64)
    sigma = max(1.0, spec.amp * float(rng.uniform(0.25, 1.0)))
    y = y + rng.normal(0.0, sigma, size=CAP_LEN)
    # 少量样本混入窄带干扰（更像真实环境的电源/串扰）
    if rng.random() < 0.4:
        k = float(rng.uniform(3.0, 40.0))
        y = y + spec.amp * float(rng.uniform(0.05, 0.25)) * np.sin(
            2.0 * np.pi * k * np.arange(CAP_LEN) / CAP_LEN + rng.uniform(0, 6.28))
    y = np.clip(np.rint(y), 0.0, 255.0).astype(np.uint8)
    return y


# ---------------------------------------------------------------------------
# 随机采样一个样本规格（域随机化 = 数据增强的主要来源）
# ---------------------------------------------------------------------------
def sample_spec(rng: np.random.Generator, label: str,
                cycles_lo: float = 4.0, cycles_hi: float = 64.0) -> CaptureSpec:
    """按标签随机采一个规格。label ∈ CLASSES"""
    # 周期数：对数均匀（覆盖示波器各种时基）
    cycles = float(np.exp(rng.uniform(math.log(cycles_lo), math.log(cycles_hi))))
    amp = float(rng.uniform(45.0, 118.0))
    if rng.random() < 0.10:
        amp = float(rng.uniform(18.0, 45.0))        # 小信号工况
    # DEC：让 K 落在合理范围（板端 DEC 1~255），仿真时按 K 反推
    dec = int(np.clip(round(FS_BASE / (cycles * rng.uniform(400.0, 9000.0))), 1, 255))
    common = dict(
        cycles=cycles,
        amp=amp,
        phase0=float(rng.random()),
        dc=float(rng.uniform(-6.0, 6.0)),
        gain=float(rng.uniform(0.92, 1.08)),
        noise_lsb=float(np.exp(rng.uniform(math.log(0.4), math.log(3.2)))),
        jitter=float(rng.uniform(0.0, 0.004)),
        dec=dec,
        dither_uniform=float(rng.uniform(0.0, 0.5)),
    )

    if label in ("sine", "square", "triangle", "sawtooth"):
        kind = {"sine": WAVE_SINE, "square": WAVE_SQUARE,
                "triangle": WAVE_TRIANGLE, "sawtooth": WAVE_SAWTOOTH}[label]
        duty = 0.5
        if label == "square":
            # ★ 干净方波只允许 ±2% 的占空比偏差，与"占空比异常"（≤0.47 / ≥0.53）
            #   严格留出可分边界。否则两个类在数据上就不可分，
            #   会制造一个人为的精度上限（第一版 0.475~0.525 就吃了这个亏）。
            duty = float(rng.uniform(0.49, 0.51))
        return CaptureSpec(kind=kind, duty=float(duty), **common)

    if label == "noise":
        return CaptureSpec(kind=WAVE_SINE, duty=0.5, **common)

    # ---- 异常类：底波形随机，异常类型即标签 ----
    kind = int(rng.choice([WAVE_SINE, WAVE_SQUARE, WAVE_TRIANGLE, WAVE_SAWTOOTH]))
    duty = 0.5
    if label == "duty_abnormal":
        # ★★ 三个必须避开的坑（前两版都踩了，直接把 duty 类变成噪声标签）：
        #   1) **正弦波的占空比没有意义**（wave_ideal 的 sine 分支根本不用 duty）。
        #      若底波形取正弦，生成的样本与"干净正弦"逐点相同 —— 纯错标签。
        #   2) **三角/锯齿的 duty 会把它变成另一种波形**：
        #      三角 duty=0.15 看起来就是锯齿波，于是 duty 类与 sawtooth 类
        #      在数据上直接冲突（实测 duty→sawtooth 误判 34/250）。
        #      ⇒ "占空比"本来就只是**方波/脉冲**的属性，
        #        本类只允许方波底波形（这也是工程上的正确定义）。
        #   3) 偏差太小低于 28×28 画布的分辨率极限：
        #      每列 = K/28 个周期，K=4 时一列就是 0.14 个周期。
        #      ⇒ "轻度"档取 [0.40,0.46]∪[0.54,0.60]，占比 15%。
        kind = WAVE_SQUARE
        if rng.random() < 0.15:      # ★ 仍然保留一批"人眼不易察觉"的轻度偏差
            duty = float(rng.choice([rng.uniform(0.40, 0.46), rng.uniform(0.54, 0.60)]))
        else:
            duty = float(rng.choice([rng.uniform(0.12, 0.36), rng.uniform(0.64, 0.88)]))
    return CaptureSpec(kind=kind, duty=duty, anomaly=label, **common)


def make_sample(rng: np.random.Generator, label: str, **kw) -> tuple:
    """返回 (samples_u8, spec, info)"""
    spec = sample_spec(rng, label, **kw)
    if label == "noise":
        y = build_noise_capture(spec, rng)
        info: Dict[str, Any] = {}
    else:
        y, info = build_capture(spec, rng, want_info=True)
    return y, spec, info


def spec_to_meta(spec: CaptureSpec, label: str, info: Optional[Dict[str, Any]] = None,
                 class_list: Optional[list] = None) -> Dict[str, Any]:
    """→ 接口 ② 规定的 NNNNN.json 内容（含 dds_params，标签可追溯）"""
    cl = class_list or CLASSES_NO_GLITCH
    base = WAVE_NAMES.get(spec.kind, "noise")
    m = {
        "label": label,
        "anomaly": spec.anomaly,
        "base_waveform": base,
        "class_index": cl.index(label) if label in cl else None,
        "freq_hz": round(spec.f_hz, 6),
        "cycles_in_capture": round(float(spec.cycles), 6),
        "amp": int(round(spec.amp)),
        "duty": round(float(spec.duty), 6),
        "noise_level": round(float(spec.noise_lsb), 6),
        "dec": int(spec.dec),
        "fs_hz": round(spec.fs_hz, 6),
        "dc_offset": round(float(spec.dc), 4),
        "gain": round(float(spec.gain), 6),
        "dds_params": {
            "waveform": int(spec.kind),
            "freq_word": freq_word_from_hz(spec.f_hz),
            "amp": int(round(spec.amp)),
            "dec": int(spec.dec),
            "phase0": round(float(spec.phase0), 6),
        },
    }
    if info:
        m["anomaly_params"] = info
    return m
