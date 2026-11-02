#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py —— 板载 Agent 的配置与限制

设计参考：DeepSeek Harness 的 `dsh-settings` / `dsh-output-retention` /
`dsh-tool-call-timeout-policy`。原则是"**所有限制都显式写出来**"，
不要散落在各处 —— 出问题时能一眼看到是哪个限制在起作用。
"""
import json
import os

HOME = os.path.expanduser("~")
CONF = os.path.join(HOME, ".agent.json")

# ---------------- 默认值 ----------------
DEFAULTS = {
    # LLM
    "api_base": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "api_key": "",
    "temperature": 0.3,
    "max_tokens": 2048,

    # ★ 语音开关（客户端设置页里能改，存在运行时覆盖文件里）
    "voice_reply": True,          # 收到回复后自动朗读
    "voice_auto_send": True,      # 语音识别完成后自动发送

    # 循环
    "max_rounds": 16,            # 一次任务最多几轮工具调用
    "llm_timeout": 120,          # 单次 LLM 请求超时（秒）
    "llm_retries": 3,            # 失败重试次数
    "tool_timeout": 60,          # 单个工具默认超时（秒）

    # ★ 输出治理（这是让模型能干活的关键，参考 dsh-output-retention + dsh-spill）
    "inline_chars": 4000,        # 工具结果超过这么多字符就落盘，只回摘要
    "inline_lines": 120,         # 行数同样有上限
    "head_lines": 40,            # 摘要里保留开头多少行
    "tail_lines": 30,            # 摘要里保留结尾多少行
    "spill_dir": os.path.join(HOME, "agent_spill"),

    # 上下文治理（参考 dsh-compaction）
    "context_chars": 120000,     # 估算上下文超过这个就压缩
    "keep_recent_rounds": 6,     # 压缩时保留最近几轮不动

    # 会话
    "session_dir": os.path.join(HOME, "agent_sessions"),

    # 安全（参考 dsh-sandbox-policy + dsh-user-approval）
    "workdir": HOME,
    "deny_patterns": [
        r"rm\s+-rf\s+/(\s|$)", r"mkfs", r"dd\s+if=.*of=/dev/",
        r">\s*/dev/mmcblk", r"boot\.scr", r"BOOT\.BIN",
        r":\(\)\s*\{.*\};\s*:", r"chmod\s+-R\s+777\s+/\s*$",
        r"shutdown", r"halt", r"poweroff",
    ],
    "confirm_patterns": [
        r"\brm\b", r"\bmv\b", r"systemctl\s+(stop|disable|mask)",
        r">\s*/etc/", r"apt-get\s+(remove|purge)", r"pip\s+uninstall",
    ],
}

_cfg = None

# ══════════════════════════════════════════════════════════════════
#  ★ 运行时覆盖文件（2026-10-02 加）
# ══════════════════════════════════════════════════════════════════
# 解决什么问题：
#   原来配置有三个来源，优先级是
#       环境变量 > CONF(.agent.json) > DEFAULTS
#   而环境变量是 systemd 在【进程启动时】注入的 —— 改了要重启 agent。
#   于是「在客户端上切模型」这件事做不到（切了也只有重启才生效）。
#
# 现在多一层覆盖文件 /home/zynq/.agent_settings.json：
#       ★ 覆盖文件 > 环境变量 > CONF > DEFAULTS
#   agent 每次 ask 前会 reload（见 load(reload=True)），所以改完立刻生效。
#
# ★ 为什么不直接改环境变量 / /etc/zynq-agent.env：
#   /etc/zynq-agent.env 是 600 root-only，agent 以 zynq 用户跑，写不了；
#   而且就算写了，已启动的进程也不会重新读。
# ★ 不能用 expanduser("~")！
#
# 踩过：agent 以【zynq 用户】跑（home=/home/zynq），
#       但 cloud-api 以【root】跑（home=/root）。
# 如果覆盖文件用 ~ 拼，cloud-api 会写到 /root/.agent_settings.json，
# 而 agent 去 /home/zynq/ 找 —— 永远读不到，「切模型」就又是假的了。
#
# ⇒ 固定路径，两个进程都指向同一个文件。
OVERRIDE = os.environ.get("XIAOBAI_SETTINGS",
                          "/home/zynq/.agent_settings.json")

# 允许被运行时覆盖的键（白名单 —— 避免客户端改到危险配置）
#
# ★ 2026-10-03 加了 extra_models：
#   用户问"能添加模型吗"。原来模型列表完全来自 DeepSeek 的 /models 接口，
#   只有官方那两三个，没法加自己的（比如别的厂商的兼容端点、或者
#   板子上以后要跑的其他模型名）。extra_models 是一个字符串列表，
#   会被 /llm/models 合并进返回结果，客户端下拉就能选到。
_OVERRIDABLE = ("model", "api_base", "api_key", "voice_reply",
                "voice_auto_send", "extra_models")


def load_override():
    """读覆盖文件，返回 dict（读不到返回 {}）"""
    try:
        with open(OVERRIDE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_override(d):
    """写覆盖文件（只留白名单里的键）"""
    cur = load_override()
    for k in _OVERRIDABLE:
        if k in d and d[k] is not None:
            cur[k] = d[k]
    tmp = OVERRIDE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OVERRIDE)
    try:
        os.chmod(OVERRIDE, 0o644)
    except Exception:
        pass
    return cur


def load(reload=False):
    global _cfg
    if _cfg is not None and not reload:
        return _cfg
    c = dict(DEFAULTS)
    try:
        with open(CONF) as f:
            c.update(json.load(f) or {})
    except Exception:
        pass
    # 环境变量优先（板上部署时用这个，避免把 key 写进文件）
    if os.environ.get("DEEPSEEK_API_KEY"):
        c["api_key"] = os.environ["DEEPSEEK_API_KEY"]
    if os.environ.get("AGENT_MODEL"):
        c["model"] = os.environ["AGENT_MODEL"]
    # ★ 运行时覆盖文件优先级最高（客户端切的模型放这里）
    ov = load_override()
    for k in _OVERRIDABLE:
        if k in ov and ov[k] not in (None, ""):
            c[k] = ov[k]
    os.makedirs(c["spill_dir"], exist_ok=True)
    os.makedirs(c["session_dir"], exist_ok=True)
    _cfg = c
    return c


def save(c):
    with open(CONF, "w") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    print("已写入", CONF)
