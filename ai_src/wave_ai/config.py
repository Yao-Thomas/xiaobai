"""
config.py —— 类别表、物理常量、服务元信息（全项目唯一真源）

★ 类别顺序是【契约】：
   · 前 8 个必须与端侧 PL CNN 完全一致、顺序一致（契约 §2.3 硬性要求 4）
   · 新增类别只能追加在后面，命名小写英文 + 下划线（契约 §2.3 硬性要求 5）
   · 模型的 logits 下标 == 本列表下标，任何地方不得重排

★ 采样口径（来自《交接任务 v1.0》与采集工具）：
   · 3PA1030 双通道 AD，10 bit，0~1023，量程 -5V~+5V
   · 电压换算 V = (lsb - 512) * 10.0 / 1024.0
   · 基础采样率 20 MSPS，抽取 dec（1~255）后 有效采样率 fs = 20MHz / dec
   · 一次采集固定 4096 点（时间顺序：最老 → 最新）
"""
from __future__ import annotations

VERSION = "2.0.0"
ENGINE = "multimodal_v1"
ENGINE_VISION = "vision_v2"
ENGINE_LLM = "llm_v2"

# ---------------------------------------------------------------------------
# 采集与物理
# ---------------------------------------------------------------------------
CAP_LEN = 4096                    # 一帧采样点数（契约固定）
ADC_BITS = 10
ADC_MAX = 1023
ADC_CENTER = 511.5                # 双极性零点码值
V_FULL_SCALE = 10.0               # -5V ~ +5V
LSB_TO_V = V_FULL_SCALE / 1024.0  # 9.765625 mV/LSB
FS_BASE = 20_000_000              # 20 MSPS

# ---------------------------------------------------------------------------
# 视觉输入几何（比端侧 28x28 大 3.4 倍边长、11.8 倍像素）
# ---------------------------------------------------------------------------
IMG = 96
N_CHANNELS = 3

# ---------------------------------------------------------------------------
# 类别表（★ 冻结顺序）
# ---------------------------------------------------------------------------
CLASSES_8 = [
    "sine", "square", "triangle", "sawtooth",
    "noise", "clipping", "signal_loss", "duty_abnormal",
]
CLASSES_EXT = [
    "pulse",        # 窄脉冲（孤立 1~3 个矩形脉冲，大部分窗口平直）
    "step",         # 阶跃（单次跳变，前后平直）
    "am",           # 调幅（包络 0.6~3 个周期）
    "fm",           # 调频（瞬时频率摆动）
    "ringing",      # 振铃（边沿后阻尼振荡）
    "double_freq",  # 双频（两个非谐波相关频率叠加）
    "hum",          # 工频干扰（极低频缓慢漂移叠加）
    "glitch",       # 毛刺（窄至 2~10 点的尖峰，叠加在正常波形上）
]
CLASSES = CLASSES_8 + CLASSES_EXT
N_CLASSES = len(CLASSES)

CN = {
    "sine": "正弦波",
    "square": "方波",
    "triangle": "三角波",
    "sawtooth": "锯齿波",
    "noise": "噪声",
    "clipping": "削顶",
    "signal_loss": "丢信号",
    "duty_abnormal": "占空比异常",
    "pulse": "窄脉冲",
    "step": "阶跃",
    "am": "调幅波",
    "fm": "调频波",
    "ringing": "振铃",
    "double_freq": "双频叠加",
    "hum": "工频干扰",
    "glitch": "毛刺",
}

# 判定要点（模型卡片 / 文本生成共用）
DEFINITION = {
    "sine": "连续平滑、上下对称、单一基频",
    "square": "高低两电平、边沿陡直、占空比接近一半",
    "triangle": "上升下降均匀、峰部尖锐",
    "sawtooth": "单方向缓变、另一侧陡峭回落",
    "noise": "无周期结构、全频带能量",
    "clipping": "峰顶或谷底被限幅削平",
    "signal_loss": "出现平线或幅度骤降段",
    "duty_abnormal": "方波高低占比明显失衡",
    "pulse": "孤立窄脉冲，脉冲之间是平直基线",
    "step": "单次电平跳变，跳变前后各一段平直",
    "am": "幅度被低频包络调制，包络起伏一个以上周期",
    "fm": "周期疏密交替、频率被调制",
    "ringing": "边沿后出现衰减振荡",
    "double_freq": "两个不相关频率同时存在、可见拍频",
    "hum": "极低频缓慢基线漂移（工频/电源纹波）",
    "glitch": "正常波形上叠加窄至几个采样点的尖峰",
}

# 类别分组：clean=正常波形；anomaly=异常；special=非周期
GROUPS = {
    "sine": "clean", "square": "clean", "triangle": "clean", "sawtooth": "clean",
    "am": "clean", "fm": "clean", "double_freq": "clean",
    "clipping": "anomaly", "signal_loss": "anomaly", "duty_abnormal": "anomaly",
    "glitch": "anomaly", "ringing": "anomaly",
    "noise": "special", "hum": "special", "pulse": "clean", "step": "clean",
}

# 质量评分是否适用于该类别（噪声/丢信号/严重削顶不谈"质量"）
QUALITY_APPLICABLE = {
    "sine": True, "square": True, "triangle": True, "sawtooth": True,
    "pulse": True, "step": True, "am": True, "fm": True,
    "ringing": True, "double_freq": True, "hum": True, "glitch": True,
    "duty_abnormal": True, "clipping": True,
    "noise": False, "signal_loss": False,
}

# 端侧 8 类的顺序索引（融合时用）
IDX_8 = {c: i for i, c in enumerate(CLASSES_8)}
IDX = {c: i for i, c in enumerate(CLASSES)}


def cn(label: str) -> str:
    return CN.get(label, label)


def onehot(index: int) -> list:
    v = [0.0] * N_CLASSES
    if 0 <= int(index) < N_CLASSES:
        v[int(index)] = 1.0
    return v
