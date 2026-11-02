"""audio_eq_env.py —— 音频 EQ 调优环境（任务 E · 目标 ②）

=============================================================================
Gym 风格环境（**只依赖 numpy + 标准库**，不依赖 gymnasium / torch）。
核心接口：

    obs = env.reset(seed=None)                        # -> float32[16]
    obs, reward, done, info = env.step(action)        # action = 8 段增益下标

★ MDP 定义
   状态(obs)   : 8 个频段的 1/3 倍频程平滑响应(dB) + 8 段当前 EQ 增益(dB)，共 16 维
   动作(action): 因子化离散 = 8 段 × 各 9 档（-12~+12 dB，步进 3 dB）
                 （8 段笛卡尔积 9^8≈4300 万会爆炸 -> 因子化，理由见 README §动作空间）
   回报(reward): 频响平坦度（1/3 倍频程平滑后相对 0dB 目标的误差负平方和）
                 - w_gain·增益惩罚
   终止(termination): RMS 误差 < 1.5 dB 提前终止；超过 max_steps 截断

★ 硬件事实（09_板子与工具链.md §3 / T-2.5 声学自测闭环）
   音频编解码 ES8388 + 功放 MD8002A -> 板载小喇叭；板载喇叭测出【低频塌陷】；
   声学自测闭环 = 放对数扫频 -> 麦克风录回 -> H(f)=Y(f)/X(f) -> 1/3 倍频程平滑 -> 频响曲线。

★ 仿真假设（需与主线负责人确认的映射，见 README §仿真假设）
   ① 房间/喇叭传递函数用解析式模拟：低频塌陷 + 1~3 个共振峰 + 高频衰减。
   ② 8 段 EQ 用"log 频率域高斯凸起"近似每个频段的幅度贡献（段间串扰小）。
      真机上 ES8388 没有参量 EQ，8 段 EQ 大概率由音频服务用软件 IIR/图示 EQ 实现，
      其 Q 值/斜率需与主线确认后对齐。
   ③ "1/3 倍频程平滑"用对 F_GRID 上各中心频率 ±1/6 倍频程窗口取平均近似。
=============================================================================
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# 常数
# ---------------------------------------------------------------------------
# 8 段 EQ 中心频率（按任务书给定，1/3 倍频程取值）
EQ_BANDS = np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0])
GAIN_LEVELS_DB = np.array([-12.0, -9.0, -6.0, -3.0, 0.0, 3.0, 6.0, 9.0, 12.0])
N_BANDS = len(EQ_BANDS)
N_GAIN = len(GAIN_LEVELS_DB)
GAIN_ZERO_IDX = 4                    # 0 dB 对应的下标

# 测量频率网格（20~20k，对数等分）
F_GRID = np.geomspace(20.0, 20000.0, 129)

# 默认（标称）房间响应参数：用于验收的固定工况
DEFAULT_ROOM = dict(
    low_db=16.0, low_fc=180.0,          # 低频塌陷深度/拐点
    hi_db=12.0, hi_fc=8000.0,           # 高频衰减深度/拐点
    peaks=((1200.0, 7.0), (5000.0, 5.0)),  # 共振峰 (中心频率Hz, 峰值dB)
)

EQ_SIGMA = 0.5        # EQ 段高斯宽度（octave）
PEAK_SIGMA = 0.4      # 共振峰高斯宽度（octave）
OBS_DIM_EQ = 2 * N_BANDS   # 8 响应 + 8 增益 = 16

DB_CLIP = 20.0        # 误差裁剪（dB）
SUCCESS_RMS_DB = 1.5  # 成功阈值：RMS 误差 < 1.5 dB


# ---------------------------------------------------------------------------
# 纯函数：频响模型与回报（可独立单测）
# ---------------------------------------------------------------------------
def room_response_db(f: np.ndarray, room: dict) -> np.ndarray:
    """房间/喇叭传递函数（dB）：低频塌陷 + 共振峰 + 高频衰减。"""
    db = np.zeros_like(f, dtype=np.float64)
    db = db - room["low_db"] / (1.0 + (f / room["low_fc"]) ** 2)
    db = db - room["hi_db"] * (f / room["hi_fc"]) ** 2 / (1.0 + (f / room["hi_fc"]) ** 2)
    for pfc, pamp in room["peaks"]:
        db = db + pamp * np.exp(-((np.log2(f / pfc) / PEAK_SIGMA) ** 2))
    return db


def eq_response_db(f: np.ndarray, gains_db: np.ndarray) -> np.ndarray:
    """8 段 EQ 的幅度贡献（dB）：每段为 log 频率域高斯凸起。"""
    db = np.zeros_like(f, dtype=np.float64)
    for fc, g in zip(EQ_BANDS, gains_db):
        db = db + float(g) * np.exp(-((np.log2(f / fc) / EQ_SIGMA) ** 2))
    return db


def third_octave_smooth(f_grid: np.ndarray, db_grid: np.ndarray, centers) -> np.ndarray:
    """1/3 倍频程平滑：对每个中心频率取 ±1/6 倍频程窗口内的 dB 均值。"""
    out = np.empty(len(centers), dtype=np.float64)
    for i, fc in enumerate(centers):
        lo = fc / (2.0 ** (1.0 / 6.0))
        hi = fc * (2.0 ** (1.0 / 6.0))
        mask = (f_grid >= lo) & (f_grid <= hi)
        out[i] = db_grid[mask].mean() if mask.any() else 0.0
    return out


def flatness_metric(resp_db: np.ndarray, target_db: float = 0.0) -> float:
    """频响平坦度：平滑后各点相对目标曲线的 dB 误差负平方和（值域 [-1,0]，越大越平）。"""
    err = np.clip(np.asarray(resp_db, dtype=np.float64) - target_db, -DB_CLIP, DB_CLIP)
    return float(-np.mean((err / DB_CLIP) ** 2))


def eq_reward(resp_db: np.ndarray, gains_db: np.ndarray, w_gain: float = 0.02) -> float:
    """回报 = 平坦度 - w_gain·增益惩罚（增益惩罚防止无限加增益）。"""
    flat = flatness_metric(resp_db)
    penalty = float(np.mean((np.asarray(gains_db, dtype=np.float64) / 12.0) ** 2))
    return flat - w_gain * penalty


def rms_db_error(resp_db: np.ndarray, target_db: float = 0.0) -> float:
    """RMS 误差（dB），用于"初始 vs 调完"的直观对比。"""
    err = np.clip(np.asarray(resp_db, dtype=np.float64) - target_db, -DB_CLIP, DB_CLIP)
    return float(np.sqrt(np.mean(err ** 2)))


def _hbar(val: float, scale: float, width: int = 10) -> str:
    """横向条（左负右正，'|'=0dB，'#'=响应），用于文本可视化。"""
    val = float(np.clip(val, -scale, scale))
    n = int(round(abs(val) / scale * width))
    if val >= 0:
        return " " * width + "|" + "#" * n + " " * (width - n)
    return " " * (width - n) + "#" * n + "|" + " " * width


# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------
class AudioEqEnv:
    """音频 EQ 调优环境（numpy only，Gym 风格）。"""

    obs_dim = OBS_DIM_EQ
    action_nvec = (N_GAIN,) * N_BANDS

    def __init__(self, seed=None, max_steps: int = 8, w_gain: float = 0.02,
                 randomize_room: bool = True):
        self.max_steps = int(max_steps)
        self.w_gain = float(w_gain)
        self.randomize_room = bool(randomize_room)
        self.rng = np.random.default_rng(seed)
        self.room = dict(DEFAULT_ROOM)
        self.gains_idx = [GAIN_ZERO_IDX] * N_BANDS
        self.steps = 0
        self.ep_info = {}

    def seed(self, seed=None):
        self.rng = np.random.default_rng(seed)

    def _sample_room(self) -> dict:
        low_db = float(self.rng.uniform(8.0, 16.0))
        low_fc = float(self.rng.uniform(150.0, 250.0))
        hi_db = float(self.rng.uniform(6.0, 14.0))
        hi_fc = float(self.rng.uniform(6000.0, 10000.0))
        n_peaks = int(self.rng.integers(1, 4))
        peaks = []
        for _ in range(n_peaks):
            pfc = float(np.exp(self.rng.uniform(np.log(400.0), np.log(9000.0))))
            pamp = float(self.rng.uniform(3.0, 9.0))
            peaks.append((pfc, pamp))
        return dict(low_db=low_db, low_fc=low_fc, hi_db=hi_db, hi_fc=hi_fc,
                    peaks=tuple(peaks))

    def _gains_db(self) -> np.ndarray:
        return GAIN_LEVELS_DB[np.asarray(self.gains_idx, dtype=np.int64)]

    def _measure(self):
        gains = self._gains_db()
        total = room_response_db(F_GRID, self.room) + eq_response_db(F_GRID, gains)
        resp = third_octave_smooth(F_GRID, total, EQ_BANDS)
        return resp, gains

    def _obs(self) -> np.ndarray:
        resp, gains = self._measure()
        resp_n = np.clip(resp / DB_CLIP, -1.0, 1.0)
        gain_n = gains / 12.0
        return np.concatenate([resp_n, gain_n]).astype(np.float32)

    # ---- Gym 风格接口 ----
    def reset(self, seed=None):
        if seed is not None:
            self.seed(seed)
        self.room = dict(DEFAULT_ROOM) if not self.randomize_room else self._sample_room()
        self.gains_idx = [GAIN_ZERO_IDX] * N_BANDS
        self.steps = 0
        self.ep_info = dict(room=self.room)
        return self._obs()

    def step(self, action):
        a = [int(x) for x in action]
        if len(a) != N_BANDS:
            raise ValueError("action 必须是长度为 %d 的序列（8 段增益下标）" % N_BANDS)
        self.gains_idx = [int(np.clip(x, 0, N_GAIN - 1)) for x in a]
        self.steps += 1

        resp, gains = self._measure()
        reward = eq_reward(resp, gains, self.w_gain)
        flat = flatness_metric(resp)
        rms_err = rms_db_error(resp)

        success = rms_err < SUCCESS_RMS_DB
        terminated = bool(success)
        truncated = bool((not terminated) and (self.steps >= self.max_steps))
        done = terminated or truncated

        info = dict(reward=float(reward), flatness=float(flat), rms_err=float(rms_err),
                    resp_db=resp.astype(np.float64), gains_db=gains.astype(np.float64),
                    gains_idx=list(self.gains_idx), room=self.room, steps=self.steps,
                    success=success, terminated=terminated, truncated=truncated)
        return self._obs(), float(reward), done, info

    # ---- 文本可视化 ----
    def render_text(self) -> str:
        resp, gains = self._measure()
        rms_err = rms_db_error(resp)
        reward = eq_reward(resp, gains, self.w_gain)

        lines = []
        lines.append("=" * 70)
        lines.append("音频 EQ 调优 | 第 %d 步 | RMS误差=%.2f dB | 回报=%+.4f"
                     % (self.steps, rms_err, reward))
        lines.append("频段(Hz): " + " ".join("%8s" % ("%d" % f) for f in EQ_BANDS))
        lines.append("响应(dB): " + " ".join("%8.1f" % r for r in resp))
        lines.append("EQ增益 : " + " ".join("%8.1f" % g for g in gains))
        lines.append("目标(dB): " + " ".join("%8.1f" % 0.0 for _ in EQ_BANDS))
        lines.append("")

        # 每频段一个横向条（左负右正，'|'=0dB，'#'=响应）
        lines.append("频响条形图 (范围 ±20 dB，'|'=0dB，'#'=响应)：")
        for i in range(N_BANDS):
            r = float(np.clip(resp[i], -20.0, 20.0))
            lines.append("  %5dHz  %s  %+6.1f dB" % (EQ_BANDS[i], _hbar(r, 20.0), r))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 可选的 gymnasium.Env 包装（import 失败时优雅跳过）
# ---------------------------------------------------------------------------
def make_gymnasium_eq_env(**kwargs):
    """返回 gymnasium.Env 包装类；若未安装 gymnasium 则返回 None。"""
    try:
        import gymnasium as gym  # noqa: F401
    except ImportError:
        return None

    class AudioEqEnvGym(gym.Env):
        def __init__(self):
            super().__init__()
            self._env = AudioEqEnv(**kwargs)
            self.observation_space = gym.spaces.Box(
                low=-1.0, high=1.0, shape=(self._env.obs_dim,), dtype=np.float32)
            self.action_space = gym.spaces.MultiDiscrete(self._env.action_nvec)

        def reset(self, *, seed=None, options=None):
            obs = self._env.reset(seed=seed)
            return obs, dict(self._env.ep_info)

        def step(self, action):
            obs, reward, done, info = self._env.step(action)
            return obs, reward, info["terminated"], info["truncated"], info

    return AudioEqEnvGym
