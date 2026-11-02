"""scope_env.py —— 示波器自动设置环境（任务 E · 目标 ①）

=============================================================================
Gym 风格环境（**只依赖 numpy + 标准库**，不依赖 gymnasium / torch，可在无
GPU 的机器上被完整单测）。核心接口：

    obs = env.reset(seed=None)                        # -> float32[obs_dim]
    obs, reward, done, info = env.step(action)        # action = (trig_idx, dec_idx, vgain_idx)

★ MDP 定义
   状态(obs)   : 64 段波形均值 + 7 个统计量 + 3 个当前设置，共 74 维，值域 [-1,1]
   动作(action): 因子化离散 = 触发电平 16 档 × DEC 16 档 × 垂直增益 5 档
                 （因子化，而非 16*16*5=1280 的笛卡尔积，理由见 README §动作空间）
   回报(reward): w1·占屏比例(60~80%) + w2·触发电平居中度 + w3·显示2~5周期 - w4·丢触发惩罚
   终止(termination): 达到成功阈值提前终止；超过 max_steps 截断(truncated)

★ 硬件事实（严格按 09_板子与工具链.md §5）
   采集深度 4096 × 8bit；基础采样率 100MHz/DIV，默认 DIV=5 -> 20 MSPS；
   时基 DEC 1~255 -> fs = 20e6 / DEC；触发电平 TRIGLEV 0~255；
   信号模型：sample = clip(round(127.5 + amp·wave(phase)), 0, 255)，
             phase = phase0 + K·n/4096，K = f × 4096 / fs（缓冲区内周期数）。

★ 仿真假设（必须与示波器负责人确认的映射，见 README §仿真假设）
   ① "垂直增益"真机没有模拟 V/div：这里建模为数字缩放因子
      vgain ∈ {0.5, 0.707, 1.0, 1.414, 2.0}，作用在采集数据上后再 clip 到 0~255。
      真机对应关系需示波器负责人确认（若对不上，就是纯仿真档位）。
   ② 触发电平在仿真中【不改变采集样本】（Auto 模式总是采集满 4096 点），
      只通过"触发有效性 / 居中度"影响回报；真机 Normal 模式丢触发会停更，本仿真用
      "触发电平落在信号 [p5,p95] 之外 -> 丢触发惩罚"来近似。
   ③ 噪声波形没有 DDS 寄存器对应（SRC[2:1] 只有 0~3），建模为高斯噪声源。
=============================================================================
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# 硬件常数
# ---------------------------------------------------------------------------
CAP_LEN = 4096
FS_BASE = 20_000_000.0            # DIV=5 时 20 MSPS
FULL_SCALE_CENTER = 127.5

# 波形编号（0~3 与 scope IP SRC[2:1] 一致；4=噪声，为额外输入源）
WAVE_SINE, WAVE_SQUARE, WAVE_TRIANGLE, WAVE_SAWTOOTH, WAVE_NOISE = 0, 1, 2, 3, 4
WAVE_NAMES = {WAVE_SINE: "sine", WAVE_SQUARE: "square", WAVE_TRIANGLE: "triangle",
              WAVE_SAWTOOTH: "sawtooth", WAVE_NOISE: "noise"}

# 垂直增益（数字缩放因子，等价 V/div 档）
VGAIN_LEVELS = (0.5, 0.7071067811865476, 1.0, 1.4142135623730951, 2.0)
N_VGAIN = len(VGAIN_LEVELS)

# 触发电平 16 档（0~255 LSB，均匀）
N_TRIG = 16
TRIG_LEVELS = tuple(int(round(i * 255.0 / (N_TRIG - 1))) for i in range(N_TRIG))

# 时基 DEC 16 档（1~255，几何分布：相邻档约 ×1.45）
DEC_LEVELS = (1, 2, 3, 4, 6, 8, 11, 15, 21, 30, 43, 61, 86, 122, 173, 255)
N_DEC = len(DEC_LEVELS)

# 观测维度：64 段波形均值 + 7 统计量 + 3 设置
N_WAVE_BINS = 64
OBS_DIM = N_WAVE_BINS + 7 + 3

# 回报权重：w1 占屏, w2 居中, w3 周期, w4 丢触发
DEFAULT_WEIGHTS = (1.0, 1.0, 1.0, 0.8)


# ---------------------------------------------------------------------------
# 纯函数：回报公式的每一子项（可独立单测）
# ---------------------------------------------------------------------------
def _trapezoid(x: float, lo: float, hi: float, ramp: float) -> float:
    """梯形隶属度：x∈[lo,hi] 满分 1，向两侧各 ramp 线性降到 0。"""
    if x < lo - ramp:
        return 0.0
    if x < lo:
        return (x - (lo - ramp)) / ramp
    if x <= hi:
        return 1.0
    if x < hi + ramp:
        return (hi + ramp - x) / ramp
    return 0.0


def occupy_reward(occupy: float, lo: float = 0.6, hi: float = 0.8, ramp: float = 0.2) -> float:
    """波形占屏比例项：占屏 60~80% 满分，向两侧 [0.4,0.6] / [0.8,1.0] 线性衰减。"""
    return _trapezoid(float(occupy), lo, hi, ramp)


def centering_reward(trig: float, mid: float, span: float) -> float:
    """触发电平居中度：trig 落在信号中位满分，落在信号边缘/之外为 0。"""
    if span <= 1e-6:
        return 0.0
    return float(np.clip(1.0 - abs(float(trig) - float(mid)) / (0.5 * float(span)), 0.0, 1.0))


def cycles_reward(K: float, lo: float = 2.0, hi: float = 5.0, ramp: float = 1.5) -> float:
    """显示周期数项：缓冲区内 2~5 个周期满分，向两侧 [0.5,2] / [5,6.5] 线性衰减。"""
    return _trapezoid(float(K), lo, hi, ramp)


def is_triggered(trig: float, p5: float, p95: float) -> bool:
    """触发有效性：触发电平落在信号 [p5,p95] 区间内视为可触发。"""
    return bool(float(p5) <= float(trig) <= float(p95))


def ideal_wave(kind: int, phase: np.ndarray, duty: float = 0.5) -> np.ndarray:
    """返回 [-1,1] 的理想波形，phase 为周期内归一化相位。"""
    p = np.mod(phase, 1.0)
    if kind == WAVE_SINE:
        return np.sin(2.0 * np.pi * p)
    if kind == WAVE_SQUARE:
        return np.where(p < duty, 1.0, -1.0)
    if kind == WAVE_TRIANGLE:
        return 1.0 - 4.0 * np.abs(p - 0.5)
    if kind == WAVE_SAWTOOTH:
        return 2.0 * p - 1.0
    raise ValueError("unknown waveform kind %r" % kind)


def compute_scope_reward(samples: np.ndarray, trig: float, dec: int,
                         wave_kind: int, f_hz: float,
                         weights=DEFAULT_WEIGHTS) -> dict:
    """计算一次采集的回报，返回逐项分解（便于调参与演示讲解）。

    samples  : 4096 个 8 位样本（uint8）
    trig     : 触发电平（0~255 LSB）
    dec      : 抽取（决定 fs = 20e6/dec）
    wave_kind: 波形编号；NOISE 时"周期数项"取满分（无周期可言）
    """
    p5, p95 = np.percentile(samples, [5.0, 95.0])
    span = float(p95 - p5)
    occupy = span / 255.0
    mid = 0.5 * float(p5 + p95)

    t1 = occupy_reward(occupy)
    t2 = centering_reward(trig, mid, span)
    triggered = is_triggered(trig, float(p5), float(p95))
    if wave_kind == WAVE_NOISE:
        K = 0.0
        t3 = 1.0
    else:
        K = f_hz * CAP_LEN / (FS_BASE / float(dec))
        t3 = cycles_reward(K)
    lost = 0.0 if triggered else 1.0

    w1, w2, w3, w4 = weights
    reward = w1 * t1 + w2 * t2 + w3 * t3 - w4 * lost
    return {
        "reward": float(reward),
        "t_occupy": float(t1), "t_center": float(t2), "t_cycles": float(t3),
        "lost": float(lost), "triggered": bool(triggered),
        "occupy": float(occupy), "mid": float(mid), "p5": float(p5),
        "p95": float(p95), "span": float(span), "K": float(K),
    }


# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------
class ScopeEnv:
    """示波器自动设置环境（numpy only，Gym 风格）。

    每轮 episode：随机一种波形 + 随机 f/幅度/直流偏置/初相 + 随机初始设置，
    策略通过多次 step 把 (触发电平, DEC, 垂直增益) 调到"稳定显示"。
    """

    obs_dim = OBS_DIM
    action_nvec = (N_TRIG, N_DEC, N_VGAIN)

    def __init__(self, seed=None, max_steps: int = 10, weights=DEFAULT_WEIGHTS,
                 f_range=(300.0, 15000.0), amp_range=(40.0, 110.0),
                 dc_range=(-10.0, 10.0), noise_range=(0.5, 3.0),
                 success_threshold=(0.9, 0.8, 0.9), fixed_wave=None,
                 success_bonus: float = 3.0, noise_amp_range=(20.0, 50.0)):
        self.max_steps = int(max_steps)
        self.weights = tuple(weights)
        self.f_range = tuple(f_range)
        self.amp_range = tuple(amp_range)
        self.dc_range = tuple(dc_range)
        self.noise_range = tuple(noise_range)
        self.success_threshold = tuple(success_threshold)
        self.fixed_wave = fixed_wave
        self.success_bonus = float(success_bonus)
        self.noise_amp_range = tuple(noise_amp_range)
        self.rng = np.random.default_rng(seed)
        # 占位，reset() 会填充
        self.wave_kind = WAVE_SINE
        self.f_hz = 1000.0
        self.amp = 80.0
        self.dc = 0.0
        self.phase0 = 0.0
        self.noise = 1.0
        self.duty = 0.5
        self.trig_idx = 8
        self.dec_idx = 8
        self.vgain_idx = 2
        self.steps = 0
        self._last_samples = np.full(CAP_LEN, 128, dtype=np.uint8)
        self.ep_info = {}

    # ---- 随机种子 ----
    def seed(self, seed=None):
        self.rng = np.random.default_rng(seed)

    # ---- 采集（严格按板卡信号模型）----
    def _capture(self) -> np.ndarray:
        dec = DEC_LEVELS[self.dec_idx]
        vgain = VGAIN_LEVELS[self.vgain_idx]
        n = np.arange(CAP_LEN, dtype=np.float64)
        if self.wave_kind == WAVE_NOISE:
            y = FULL_SCALE_CENTER + self.dc + self.rng.normal(0.0, self.amp, size=CAP_LEN)
        else:
            K = self.f_hz * CAP_LEN / (FS_BASE / float(dec))
            phase = self.phase0 + K * n / CAP_LEN
            w = ideal_wave(self.wave_kind, phase, self.duty)
            y = FULL_SCALE_CENTER + self.dc + self.amp * w
            y = y + self.rng.normal(0.0, self.noise, size=CAP_LEN)
        # 垂直增益：数字缩放（围绕中心 128），再 clip 到 0~255
        y = (y - FULL_SCALE_CENTER) * vgain + FULL_SCALE_CENTER
        y = np.clip(np.rint(y), 0.0, 255.0).astype(np.uint8)
        return y

    # ---- 观测 ----
    def _obs(self) -> np.ndarray:
        samples = self._last_samples
        dec = DEC_LEVELS[self.dec_idx]
        # 64 段均值（波形形状，值域 [-1,1]）
        bins = samples.reshape(N_WAVE_BINS, CAP_LEN // N_WAVE_BINS).mean(axis=1)
        wave = (bins - 128.0) / 128.0
        p5, p95 = np.percentile(samples, [5.0, 95.0])
        span = float(p95 - p5)
        occupy = span / 255.0
        mean = float(samples.mean())
        std = float(samples.std())
        K = 0.0 if self.wave_kind == WAVE_NOISE else (self.f_hz * CAP_LEN / (FS_BASE / float(dec)))
        stats = np.array([
            (mean - 128.0) / 128.0,                                   # 直流偏置
            float(np.clip(std / 128.0, 0.0, 1.0)) * 2.0 - 1.0,       # 展宽
            (p5 - 128.0) / 128.0,                                     # 下包络
            (p95 - 128.0) / 128.0,                                    # 上包络
            (span / 128.0) - 1.0,                                     # 峰峰值
            2.0 * occupy - 1.0,                                       # 占屏
            float(np.clip(np.log2(max(K, 0.03)) / 6.0, -1.0, 1.0)),  # 周期数估计（log2，K∈[0.03,64] 全分辨率）
        ], dtype=np.float32)
        settings = np.array([
            TRIG_LEVELS[self.trig_idx] / 255.0 * 2.0 - 1.0,           # 触发电平（线性 LSB）
            (self.dec_idx / (N_DEC - 1.0)) * 2.0 - 1.0,               # 时基档位（几何分布→log 空间线性）
            (self.vgain_idx / (N_VGAIN - 1.0)) * 2.0 - 1.0,           # 增益档位（几何分布→log 空间线性）
        ], dtype=np.float32)
        return np.concatenate([wave.astype(np.float32), stats, settings]).astype(np.float32)

    # ---- Gym 风格接口 ----
    def reset(self, seed=None):
        if seed is not None:
            self.seed(seed)
        self.wave_kind = (int(self.rng.integers(0, 5)) if self.fixed_wave is None
                          else int(self.fixed_wave))
        self.f_hz = float(np.exp(self.rng.uniform(np.log(self.f_range[0]), np.log(self.f_range[1]))))
        # 噪声的 amp 解释为噪声标准差（用独立较小的范围，避免重度削顶）
        self.amp = float(self.rng.uniform(*(self.noise_amp_range if self.wave_kind == WAVE_NOISE
                                            else self.amp_range)))
        self.dc = float(self.rng.uniform(*self.dc_range))
        self.phase0 = float(self.rng.random())
        self.noise = float(self.rng.uniform(*self.noise_range))
        self.duty = 0.5
        self.trig_idx = int(self.rng.integers(0, N_TRIG))
        self.dec_idx = int(self.rng.integers(0, N_DEC))
        self.vgain_idx = int(self.rng.integers(0, N_VGAIN))
        self.steps = 0
        self._last_samples = self._capture()
        self.ep_info = dict(wave_kind=self.wave_kind, wave_name=WAVE_NAMES[self.wave_kind],
                            f_hz=self.f_hz, amp=self.amp, dc=self.dc,
                            phase0=self.phase0, noise=self.noise)
        return self._obs()

    def step(self, action):
        a = [int(x) for x in action]
        if len(a) != 3:
            raise ValueError("action 必须是长度为 3 的序列 (trig_idx, dec_idx, vgain_idx)")
        self.trig_idx = int(np.clip(a[0], 0, N_TRIG - 1))
        self.dec_idx = int(np.clip(a[1], 0, N_DEC - 1))
        self.vgain_idx = int(np.clip(a[2], 0, N_VGAIN - 1))

        self._last_samples = self._capture()
        self.steps += 1

        trig = TRIG_LEVELS[self.trig_idx]
        dec = DEC_LEVELS[self.dec_idx]
        r = compute_scope_reward(self._last_samples, trig, dec,
                                 self.wave_kind, self.f_hz, self.weights)
        th0, th1, th2 = self.success_threshold
        success = (r["t_occupy"] >= th0 and r["t_center"] >= th1
                   and r["t_cycles"] >= th2 and r["lost"] == 0.0)
        terminated = bool(success)
        truncated = bool((not terminated) and (self.steps >= self.max_steps))
        done = terminated or truncated
        reward = float(r["reward"]) + (self.success_bonus if success else 0.0)

        info = dict(r, **self.ep_info,
                    reward=reward, reward_base=float(r["reward"]),
                    success_bonus=self.success_bonus if success else 0.0,
                    trig=trig, dec=dec, vgain=VGAIN_LEVELS[self.vgain_idx],
                    trig_idx=self.trig_idx, dec_idx=self.dec_idx, vgain_idx=self.vgain_idx,
                    steps=self.steps, success=success,
                    terminated=terminated, truncated=truncated)
        return self._obs(), reward, done, info

    # ---- 文本可视化（演示"肉眼可见"）----
    def render_text(self, width: int = 76, height: int = 22) -> str:
        samples = self._last_samples
        width = int(np.clip(width, 20, CAP_LEN))
        trig = TRIG_LEVELS[self.trig_idx]
        dec = DEC_LEVELS[self.dec_idx]
        vgain = VGAIN_LEVELS[self.vgain_idx]
        r = compute_scope_reward(samples, trig, dec, self.wave_kind, self.f_hz, self.weights)
        w1, w2, w3, w4 = self.weights

        lines = []
        lines.append("=" * (width + 2))
        lines.append("示波器自动设置 | 波形=%s  f=%.0fHz  amp=%.0f  dc=%.1f"
                     % (WAVE_NAMES[self.wave_kind], self.f_hz, self.amp, self.dc))
        lines.append("动作: TRIG=%d(%d/%d)  DEC=%d  VGAIN=%.3f(idx%d)  fs=%.3fMHz  K=%.2f"
                     % (trig, self.trig_idx, N_TRIG - 1, dec, vgain, self.vgain_idx,
                        FS_BASE / dec / 1e6, r["K"]))
        lines.append("回报分解: %+.3f(占屏) + %+.3f(居中) + %+.3f(周期) - %+.3f(丢触发) = %+.3f"
                     % (w1 * r["t_occupy"], w2 * r["t_center"], w3 * r["t_cycles"],
                        w4 * r["lost"], r["reward"]))
        lines.append("occupy=%.2f  mid=%.1f  span=%.1f  triggered=%d  success=%s"
                     % (r["occupy"], r["mid"], r["span"], int(r["triggered"]),
                        ("yes" if (r["t_occupy"] >= self.success_threshold[0]
                                   and r["t_center"] >= self.success_threshold[1]
                                   and r["t_cycles"] >= self.success_threshold[2]
                                   and r["lost"] == 0.0) else "no")))

        # 每列取 min/max
        col_lo = np.zeros(width, dtype=np.float64)
        col_hi = np.zeros(width, dtype=np.float64)
        step = CAP_LEN // width
        for c in range(width):
            seg = samples[c * step:(c + 1) * step]
            col_lo[c] = seg.min()
            col_hi[c] = seg.max()

        trig_row = int(round((255.0 - trig) / 255.0 * (height - 1)))
        band_h = 255.0 / (height - 1)
        for row in range(height):
            level_top = 255.0 - row * band_h
            level_bot = 255.0 - (row + 1) * band_h
            chars = []
            for c in range(width):
                lo, hi = col_lo[c], col_hi[c]
                overlaps = (hi >= level_bot) and (lo <= level_top)
                if overlaps:
                    chars.append("#" if (hi - lo) > 2.0 * band_h else ":")
                elif row == trig_row:
                    chars.append("-")
                else:
                    chars.append(" ")
            lines.append("|" + "".join(chars) + "|")
        lines.append("|" + "0".ljust(width) + "|")  # 底部电平标注
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 可选的 gymnasium.Env 包装（import 失败时优雅跳过）
# ---------------------------------------------------------------------------
def make_gymnasium_scope_env(**kwargs):
    """返回 gymnasium.Env 包装类；若未安装 gymnasium 则返回 None。"""
    try:
        import gymnasium as gym  # noqa: F401
    except ImportError:
        return None

    class ScopeEnvGym(gym.Env):
        def __init__(self):
            super().__init__()
            self._env = ScopeEnv(**kwargs)
            self.observation_space = gym.spaces.Box(
                low=-1.0, high=1.0, shape=(self._env.obs_dim,), dtype=np.float32)
            self.action_space = gym.spaces.MultiDiscrete(self._env.action_nvec)

        def reset(self, *, seed=None, options=None):
            obs = self._env.reset(seed=seed)
            return obs, dict(self._env.ep_info)

        def step(self, action):
            obs, reward, done, info = self._env.step(action)
            return obs, reward, info["terminated"], info["truncated"], info

    return ScopeEnvGym
