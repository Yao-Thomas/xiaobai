# -*- coding: utf-8 -*-
"""
config.py —— 云端推理服务（任务 G/H）所有可调参数的集中地

所有参数都支持 SERVE_ 前缀环境变量覆盖，lab415 部署时无需改代码。
本模块零第三方依赖（仅标准库），可被 router/sync_store/client 安全引用。
"""
import os as _os

# ---------------------------------------------------------------------------
# 路径：src/serve -> src -> 项目根（ai_training）
# ---------------------------------------------------------------------------
_HERE = _os.path.dirname(_os.path.abspath(__file__))     # .../src/serve
_SRC = _os.path.dirname(_HERE)                            # .../src
_PROJ = _os.path.dirname(_SRC)                            # .../ai_training


def _env_str(name, default):
    v = _os.environ.get(name)
    return default if (v is None or v == "") else v


def _env_int(name, default):
    v = _os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name, default):
    v = _os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 服务地址
# ---------------------------------------------------------------------------
HOST = _env_str("SERVE_HOST", "0.0.0.0")
PORT = _env_int("SERVE_PORT", 8000)

# ---------------------------------------------------------------------------
# 简单鉴权：api_key 从本配置读，SERVE_API_KEY 可覆盖；未配置(空串)时不校验
# ---------------------------------------------------------------------------
API_KEY = _env_str("SERVE_API_KEY", "")

# ---------------------------------------------------------------------------
# 分级推理参数
# ---------------------------------------------------------------------------
CLOUD_TIMEOUT_S = _env_float("SERVE_CLOUD_TIMEOUT", 2.5)          # 云端调用超时（契约 2.5s）
CONFIDENCE_THRESHOLD = _env_float("SERVE_CONFIDENCE_THRESHOLD", 0.7)  # 低于此值送云端
CLIENT_RETRIES = _env_int("SERVE_CLIENT_RETRIES", 1)              # 客户端重试次数
CLIENT_BACKOFF_S = _env_float("SERVE_CLIENT_BACKOFF", 0.3)        # 重试退避（秒）

# ---------------------------------------------------------------------------
# 模型后端
# ---------------------------------------------------------------------------
# 波形分类量化模型目录：若存在则加载（纯 numpy int8 前向），否则用内置启发式占位分类器
MODEL_DIR = _env_str("SERVE_MODEL_DIR",
                     _os.path.join(_PROJ, "deliverables", "quantized_model"))
# 预处理形态（src/common/preprocess.py 的 mode）。任务书指定用 "wdens"。
# 若交付的 model_spec.json 声明了不同 input_type（如 "stft"），改这里或设 SERVE_PREPROCESS_MODE。
PREPROCESS_MODE = _env_str("SERVE_PREPROCESS_MODE", "wdens")

# ---------------------------------------------------------------------------
# 类别表（★ 冻结，顺序 = 模型输出下标，禁止改，见 docs/00_接口冻结单.md §5）
# ---------------------------------------------------------------------------
CLASSES = ["sine", "square", "triangle", "sawtooth", "noise",
           "glitch", "clipping", "signal_loss", "duty_abnormal"]

# ---------------------------------------------------------------------------
# 任务 H：分布式 agent 同步存储
# ---------------------------------------------------------------------------
SYNC_DB_PATH = _env_str("SERVE_SYNC_DB",
                        _os.path.join(_PROJ, "data", "sync.db"))
BOARD_RECENT_N = _env_int("SERVE_BOARD_RECENT_N", 50)   # 板子本地只存最近 N 条


def to_dict():
    """导出全部配置（隐藏 API_KEY 明文，只报是否已配置）"""
    return {
        "host": HOST,
        "port": PORT,
        "api_key_configured": bool(API_KEY),
        "cloud_timeout_s": CLOUD_TIMEOUT_S,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "client_retries": CLIENT_RETRIES,
        "client_backoff_s": CLIENT_BACKOFF_S,
        "model_dir": MODEL_DIR,
        "preprocess_mode": PREPROCESS_MODE,
        "classes": list(CLASSES),
        "sync_db_path": SYNC_DB_PATH,
        "board_recent_n": BOARD_RECENT_N,
    }
