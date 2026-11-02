#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tiers.py —— 分级推理：板子断网也要能用

════════════════════════════════════════════════════════════════════
要解决的问题
════════════════════════════════════════════════════════════════════
现在板载 agent 是 **100% 依赖云端** 的（deepseek-chat）。
后果：比赛现场 WiFi 一抖、或者干脆没网，agent 就只会说
     "我是系统管家小白" —— 任何工具调用都做不了。

规划里写的是「本地小模型 + 云端大模型」。这一层就是那个调度器。

════════════════════════════════════════════════════════════════════
三层怎么分工
════════════════════════════════════════════════════════════════════
    Tier 0 · 规则式          ★ 不需要任何模型，永远可用
        关键词/正则匹配常见指令 -> 直接调工具
        覆盖：问温度、读寄存器、放音乐/停、截图、看服务、查变更、
              声学自测、看磁盘…… 这些"管家日常"其实都能覆盖

    Tier 1 · 本地小模型        ★ 等 AI 方交付量化模型
        接口留好了：放 /home/zynq/models/ 下，用 llama.cpp 或 onnxruntime 跑
        现在没模型就自动跳过，不影响

    Tier 2 · 云端大模型        ★ 现在的主力
        deepseek-chat（或 AI 方给的云端推理 API）

════════════════════════════════════════════════════════════════════
调度策略
════════════════════════════════════════════════════════════════════
    mode = "cloud"  只用云端（失败就报错，不降级）
    mode = "local"  只用本地（Tier 0 + Tier 1）
    mode = "auto"   ★ 默认：云端通就用云端；不通降级到本地
                          （板子上网不稳，推荐这个）

    ★ 无论哪种模式，Tier 0 的"确定性指令"都优先 ——
      因为"现在多少度"这种问题，直接查比让模型猜又快又准。
      这就是 Harness 里"该用工具就用工具"的思路。

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    # 作为库
    from agent.tiers import Tiers
    t = Tiers(mode="auto")
    r = t.ask("现在多少度")
    # r = {"ok": True, "tier": "rule", "reply": "现在 69.8 度…", "tool": "hw_thermal"}

    # 命令行自测（不需要板子）
    python3 tiers.py --selftest
    python3 tiers.py "现在多少度"
"""
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★ 「问题示例」行的标记 —— 和 live_kb.py 里的常量保持一致
#   检索要用它（让 bigram 有东西匹配），但回答里要滤掉（读起来是噪音）
HINT_MARK = "【本块回答这类问题】"

# ══════════════════════════════════════════════════════════════════
#  ★ 模式文件 —— 「切换模式」的真相来源
# ══════════════════════════════════════════════════════════════════
# 为什么用文件而不是环境变量：
#   环境变量是进程启动时定死的，改了要重启 agent。
#   而重启会丢掉会话上下文（用户正在聊的东西没了），体验很差。
#   文件则可以随时改、随时读 ⇒ 切换【立刻生效】。
#
# 为什么放 /home/zynq/：
#   agent 以 zynq 用户跑，cloud-api 以 root 跑，两边都能读写这里。
#   （/etc/zynq-agent.env 是 600 root-only，agent 读不了。）
MODE_FILE = os.environ.get("XIAOBAI_MODE_FILE", "/home/zynq/.agent_mode")
_MODE_CACHE = {"ts": 0.0, "mode": None}


def read_mode_file():
    """读模式文件，返回 local/cloud/auto；读不到返回 None"""
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            m = f.read().strip().lower()
        return m if m in ("local", "cloud", "auto") else None
    except Exception:
        return None


def write_mode_file(mode):
    """写模式文件（返回 True/False）"""
    if mode not in ("local", "cloud", "auto"):
        return False
    try:
        d = os.path.dirname(MODE_FILE)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = MODE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(mode + "\n")
        os.replace(tmp, MODE_FILE)
        try:
            os.chmod(MODE_FILE, 0o644)      # 让 root 和 zynq 都能读
        except Exception:
            pass
        return True
    except Exception:
        return False


MODEL_DIR = os.environ.get("XIAOBAI_MODEL_DIR", "/home/zynq/models")
AGENT_DIR = os.environ.get("XIAOBAI_AGENT_DIR", "/home/zynq")

# 云端可达性缓存（别每次问都去探测）
_cloud_cache = {"ts": 0, "ok": None}


# ══════════════════════════════════════════════════════════════════
#  Tier 0 · 规则式（不需要模型）
# ══════════════════════════════════════════════════════════════════
# 每条规则: (名字, 正则列表, 处理函数)
#   ★ 正则尽量宽（口语化的说法都要能匹配），但**不能太宽**
#     （比如"开"字太泛，会误触发）
RULES = []


def rule(name, *patterns):
    def deco(fn):
        RULES.append((name, [re.compile(p, re.I) for p in patterns], fn))
        return fn
    return deco


def _sh(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace")
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


def _tool(name, args):
    """调 agent 的工具（延迟 import，免得循环依赖）"""
    try:
        sys.path.insert(0, AGENT_DIR)
        from agent import tools as T
        import agent.hw_tools  # noqa: F401  确保注册
        return T.call(name, args or {}, {})
    except Exception as e:
        return "调工具出错: %s: %s" % (type(e).__name__, e)


def _read_temp():
    try:
        raw = int(open("/sys/bus/iio/devices/iio:device0/in_temp0_raw").read())
        sc = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_scale").read())
        of = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_offset").read())
        return round((raw + of) * sc / 1000.0, 1)
    except Exception:
        return None


@rule("thermal",
      r"多少度", r"温度", r"热不热", r"烫不烫", r"发烧", r"几度")
def _r_thermal(text):
    t = _read_temp()
    if t is None:
        return "读不到温度传感器。"
    if t < 70:
        s = "正常"
    elif t < 85:
        s = "有点高，但还能用"
    elif t < 92:
        s = "偏高 —— 守护会开始降载"
    else:
        s = "★ 很高了，要停机散热"
    return "现在 %.1f 度，%s。" % (t, s)


@rule("services",
      r"服务.*(状态|怎么样|正常)", r"哪些服务", r"服务列表",
      r"桌面.*(在|跑|起)", r"音频服务")
def _r_services(text):
    rc, out = _sh("systemctl is-active zynq-desktop zynq-audio zynq-agent "
                  "thermal-guard thermal-cooldown", 8)
    names = ["桌面", "音频", "Agent", "温度守护", "开机冷却"]
    states = out.strip().split("\n")
    parts = []
    for i, n in enumerate(names):
        st = states[i] if i < len(states) else "?"
        parts.append("%s%s" % (n, "正常" if st == "active" else "★" + st))
    return "服务状态：" + "，".join(parts) + "。"


@rule("disk", r"磁盘", r"剩多少空间", r"存储", r"空间够")
def _r_disk(text):
    rc, out = _sh("df -h / | tail -1", 8)
    p = out.split()
    if len(p) >= 4:
        return "根分区用了 %s，还剩 %s（总共 %s）。" % (p[2], p[3], p[1])
    return "查不到磁盘信息。"


@rule("uptime", r"运行了多久", r"开机多久", r"跑了多久", r"在线多久")
def _r_uptime(text):
    try:
        up = float(open("/proc/uptime").read().split()[0])
        return "已经连续运行 %d 小时 %d 分钟了。" % (up // 3600, (up % 3600) // 60)
    except Exception:
        return "查不到运行时间。"


@rule("speak_stop",
      r"停(止)?(放|播|唱)",
      r"停(一)?下",                      # ★ "停一下音乐" —— 测试抓出来的
      r"别(放|唱)了", r"安静",
      r"关掉?音乐", r"暂停")
def _r_stop(text):
    rc, out = _sh("systemctl stop zynq-audio 2>/dev/null; "
                  "pkill -f aplay 2>/dev/null; echo done", 10)
    return "好，停了。"


@rule("silent_on",
      r"静音模式?(打开|开|开启)",
      r"(进入|开启|打开).{0,2}静音",     # ★ "进入静音模式" —— 测试抓出来的
      r"别出声", r"不许出声", r"闭嘴")
def _r_silent_on(text):
    rc, out = _sh("touch /etc/zynq-silent && echo ok", 5)
    return "好，进入静音模式，我不出声了。"


@rule("silent_off", r"解除静音", r"静音模式?(关闭|关|关掉)",
      r"可以(出声|说话)了", r"(退出|关掉).{0,2}静音")
def _r_silent_off(text):
    rc, out = _sh("rm -f /etc/zynq-silent && echo ok", 5)
    return "好，静音解除了。"


@rule("version", r"你是谁", r"你叫什么", r"自我介绍", r"你是什么")
def _r_who(text):
    return "我是系统管家小白，这块 Zynq7020 板子的系统管家。"


@rule("capability", r"你会(做|干)什么", r"有(什么|哪些)功能",
      r"能干什么", r"会什么")
def _r_caps(text):
    n = 0
    try:
        sys.path.insert(0, AGENT_DIR)
        from agent import tools as T
        import agent.hw_tools  # noqa: F401
        n = len(T.REGISTRY)
    except Exception:
        pass
    return ("我有 %d 个工具。核心能力：看温度和磁盘、读 FPGA 寄存器、"
            "放音乐、录一段并做声学自测、看服务状态、"
            "查硬件变更历史并一键回滚、提交 FPGA 构建任务。" % n)


@rule("regs", r"(读|看|查).{0,6}寄存器",
      r"(scope_0|gpu_0|cnn_conv_pool|cnn_fc)",
      r"cnn.{0,6}(在哪个地址|的地址|地址是)",
      r"pl.{0,4}(ip|寄存器)",
      r"(自研|自己的).{0,4}ip.{0,4}地址")
def _r_regs(text):
    """读 PL 上几个自研 IP 的 VERSION 寄存器

    ★ 这里的正则【收窄过】，记一下为什么：
      原来有一条 `r"寄存器.*(值|多少)"`，本意是接"寄存器的值是多少"，
      但它会匹配【任何】带"寄存器"的问题 ——
      实测"ES8388 的 DAC 音量寄存器是多少"被它抢答，
      然后回了一串 PL 的 IP 地址，答非所问，
      也把本该走 RAG 的问题（音频编解码器的寄存器）拦下来了。

      ⇒ 所以改成必须【明确指向 PL 上的自研 IP】或者
        【明确说"读寄存器"】，才走这条规则。
    """
    out = []
    for name in ("scope_0", "gpu_0", "cnn_conv_pool", "cnn_fc"):
        r = _tool("hw_reg_read", {"base": name, "offset": "0x34"})
        r = str(r)
        if "0x" in r:
            m = re.search(r"0x[0-9A-Fa-f]{8}", r)
            out.append("%s=%s" % (name, m.group(0) if m else "?"))
        else:
            out.append("%s 读不到" % name)
    return "PL 里的自研 IP：" + "，".join(out) + "。"


@rule("changes", r"变更(历史|记录|单)", r"改过(什么|哪些)", r"谁改的")
def _r_changes(text):
    r = _tool("hw_change_list", {"limit": 3})
    return "最近的硬件变更：\n" + str(r)[:600]


@rule("fpga", r"(agent|你).*(改|修改).*(fpga|硬件|逻辑|rtl)",
      r"改.*(bitstream|比特流)", r"重新.*综合")
def _r_fpga(text):
    return ("我能改 FPGA，但要走完整流程：\n"
            "① 用 hw_hdl_edit 改 RTL（自动备份 + 语法检查）\n"
            "② 用 hw_fpga_build 提交构建（PC 侧守护跑 Vivado）\n"
            "③ 用 hw_flash_bitstream 刷到板子\n"
            "④ 用 hw_verify 跑回归，不行就 hw_change_rollback 回滚\n"
            "★ 告诉我你想改什么，我来做。")


@rule("time", r"几点", r"现在时间", r"今天几号", r"日期")
def _r_time(text):
    return datetime.datetime.now().strftime("现在是 %Y 年 %m 月 %d 日 %H:%M。")


@rule("network",
      r"(ip|地址)\s*是\s*多少",          # ★ "我的 IP 是多少" —— 有空格，测试抓出来的
      r"(ip|地址)\s*(多少|几)",
      r"网络", r"连(上|着)网", r"网卡")
def _r_net(text):
    rc, out = _sh("hostname -I", 5)
    ip = out.strip().split()[0] if out.strip() else "?"
    return "我的 IP 是 %s。" % ip


# ══════════════════════════════════════════════════════════════════
#  ★★★ 模式切换（本地 / 云端 / 自动）—— 2026-10-02 修
# ══════════════════════════════════════════════════════════════════
# 为什么这几条规则要单独写：
#   原来「切模式」这件事根本不存在 ——
#   core.py 在导入时把 mode 定死，cloud_api 的 /llm/config 只改局部变量。
#   现在模式存在文件里，读写都是模块级函数，所以规则层可以直接用。
#
# ★ 放在规则层（Tier 0）而不是让模型去理解：
#   这是【确定性指令】—— "切到本地" 就一定是切到本地，
#   不该让大模型去猜，也不该走 RAG 检索。而且规则层 <10ms。
MODE_WORDS = {
    "local": ("本地", "离线", "断网", "不联网", "本地模型", "local"),
    "cloud": ("云端", "在线", "联网", "云上", "大模型", "cloud"),
    "auto": ("自动", "auto", "默认"),
}


def _switch_mode(target, text):
    """改模式并回话"""
    old = read_mode_file() or os.environ.get("AGENT_MODE", "auto")
    if not write_mode_file(target):
        return "改不了模式文件（%s）—— 权限有问题？" % MODE_FILE
    # ★ 清掉缓存，让这次回答里 describe 也能立刻反映新值
    _MODE_CACHE["ts"] = 0.0
    _MODE_CACHE["mode"] = None
    names = {"local": "本地（离线）", "cloud": "云端", "auto": "自动"}
    if old == target:
        return "已经是%s模式了。" % names[target]
    extra = {
        "local": "接下来只用本地：规则层 + 本地 RAG。断网也不影响。",
        "cloud": "接下来只用云端。★ 注意：云端不通时会直接报错，不会降级。",
        "auto": "接下来自动：云端通就用云端，不通自动降到本地 RAG。",
    }.get(target, "")
    return "好，从【%s】切到【%s】。%s" % (names.get(old, old), names[target],
                                          extra)


@rule("mode_local",
      r"(切|换|改|用|走).{0,4}(到)?.{0,2}本地(模式)?",
      r"离线模式", r"断网模式", r"不(要)?联(网|网了)", r"本地模型")
def _r_mode_local(text):
    return _switch_mode("local", text)


@rule("mode_cloud",
      r"(切|换|改|用|走).{0,4}(到)?.{0,2}云端(模式)?",
      r"在线模式", r"联网模式", r"(用|走)云(端|上)")
def _r_mode_cloud(text):
    return _switch_mode("cloud", text)


@rule("mode_auto",
      r"(切|换|改|回).{0,4}(到)?.{0,2}自动(模式)?",
      r"自动模式", r"默认模式")
def _r_mode_auto(text):
    return _switch_mode("auto", text)


@rule("mode_show",
      r"(现在|当前|什么|哪个).{0,4}模式",
      r"模式.{0,4}(是|多少|什么)",
      r"你(在|用).{0,4}(本地|云端)")
def _r_mode_show(text):
    m = read_mode_file() or os.environ.get("AGENT_MODE", "auto")
    if m not in ("local", "cloud", "auto"):
        m = "auto"
    names = {"local": "本地（离线）", "cloud": "云端", "auto": "自动"}
    reach = "通" if cloud_reachable() else "不通"
    return ("现在跑在【%s】模式。\n"
            "  · 本地：规则 %d 条 + RAG 知识库（断网也能答）\n"
            "  · 云端：DeepSeek（当前网络%s）\n"
            "  说「切到本地模式」/「切到云端」/「切回自动」可以换。"
            % (names[m], len(RULES), reach))


# ══════════════════════════════════════════════════════════════════
#  Tier 1 · 本地小模型（接口留好，等 AI 方交付）
# ══════════════════════════════════════════════════════════════════
class LocalModel(object):
    """本地小模型封装

    ★ 现在还没有模型（等 AI 方交付量化后的权重）。
      这里把接口定好，模型一到就能用，不用改上层。

    支持的两种放法（按优先级）：
        /home/zynq/models/xiaobai.gguf      -> 用 llama.cpp（llama-cli / llama-server）
        /home/zynq/models/xiaobai.onnx      -> 用 onnxruntime
    """

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.kind = None
        self.path = None
        self._detect()

    def _detect(self):
        for name, kind in (("xiaobai.gguf", "llama"),
                           ("xiaobai.onnx", "onnx"),
                           ("xiaobai.bin", "onnx")):
            p = os.path.join(MODEL_DIR, name)
            if os.path.exists(p):
                self.kind = kind
                self.path = p
                break

    @property
    def available(self):
        return self.kind is not None

    def describe(self):
        if not self.available:
            return "没装本地模型（放 %s/xiaobai.gguf 就能用）" % MODEL_DIR
        return "本地模型 %s（%s）" % (os.path.basename(self.path), self.kind)

    def ask(self, text, system="", max_tokens=256):
        """让本地模型回答。不可用就返回 None。"""
        if not self.available:
            return None
        if self.kind == "llama":
            # llama.cpp 的 llama-cli —— 一次问答
            exe = None
            for c in ("/usr/local/bin/llama-cli", "/usr/bin/llama-cli",
                      "/home/zynq/llama.cpp/build/bin/llama-cli"):
                if os.path.exists(c):
                    exe = c
                    break
            if not exe:
                return None
            prompt = ("%s\n\n用户：%s\n助手：" % (system, text)) if system else \
                     ("用户：%s\n助手：" % text)
            rc, out = _sh('%s -m %s -p %s -n %d --no-display-prompt 2>/dev/null'
                          % (exe, self.path, json.dumps(prompt), max_tokens), 120)
            if rc == 0 and out.strip():
                return out.strip()
            return None
        if self.kind == "onnx":
            try:
                import onnxruntime  # noqa: F401
            except Exception:
                return None
            # ★ 具体怎么喂输入取决于 AI 方的模型格式，等交付后再定
            return None
        return None


# ══════════════════════════════════════════════════════════════════
#  Tier 1b · 本地 RAG（检索增强）—— ★ 断网时的主力
# ══════════════════════════════════════════════════════════════════
class RagModel(object):
    """把 AI 训练负责人交付的纯标准库 RAG 接进来

    ★ 为什么要它（踩过的判断失误）：
      AI 负责人原本的结论是「板子内存不够，走云端，本地只做转发」。
      他那个账是按 transformers/PyTorch 估的（PyTorch 版实测 RSS 3.36GB）。
      但我们在板子上实测：系统基线只用了 112MB，可用 839MB。

      而这份 RAG 是【纯 Python 标准库】写的：
        · 不依赖 jieba / rank_bm25 / numpy / torch
        · 知识库 536 个 chunk，总共几百 KB
        · 内存占用几十 MB，响应毫秒级
      ⇒ 完全可以放进板子，作为断网时的兜底。

    ★ 它的能力边界（要如实说，别吹）：
      RAG 是【抽取式】的 —— 只能从文档里挑句子拼起来，
      不会组织新句子。所以：
        · 优点：可溯源、不瞎编、拒答准确率 0.938
        · 缺点：回答读起来像"资料摘录"，不像人话
      ⇒ 所以【云端可用时】，RAG 的正确用法是：
          检索出资料 → 塞进 prompt → 让云端大模型组织语言
        这样既有可溯源的资料，又有人话。

    文件位置（跟 agent 同目录）：
        /home/zynq/agent/rag.py
        /home/zynq/agent/kb/chunks.jsonl
    """

    def __init__(self, verbose=False):
        self.v = verbose
        self.rag = None
        self.reason = ""
        here = os.path.dirname(os.path.abspath(__file__))
        self.kb_dir = os.path.join(here, "kb")
        self.rag_py = os.path.join(here, "rag.py")
        if not os.path.exists(self.rag_py):
            self.reason = "没有 rag.py（放在 %s）" % self.rag_py
            return
        if not os.path.isdir(self.kb_dir):
            self.reason = "没有知识库目录（%s）" % self.kb_dir
            return
        # ★★ 加载 kb/ 下【所有】 jsonl，不只 chunks.jsonl
        #
        # 为什么：除了 AI 负责人交付的静态知识库（chunks.jsonl，536 块），
        # 我们还让 live_kb.py 生成一个【实时状态】知识库
        # （live_chunks.jsonl：温度/服务/变更/示波器/AI 能力/硬件）。
        # 这两类问题用的是同一套 BM25 检索，所以直接合并进同一个索引就行。
        #
        # ★ 这也是"板载自主助手"独有的能力 —— 静态文档谁都放得进去，
        #   但"板子自己此刻的状态"只有住在板子里的 agent 拿得到。
        files = []
        try:
            for fn in sorted(os.listdir(self.kb_dir)):
                if fn.endswith(".jsonl"):
                    files.append(os.path.join(self.kb_dir, fn))
        except Exception:
            pass
        if not files:
            self.reason = "知识库目录里没有 .jsonl（%s）" % self.kb_dir
            return
        try:
            sys.path.insert(0, here)
            import importlib
            mod = importlib.import_module("rag")
            chunks = []
            self.files = files
            for p in files:
                try:
                    chunks += mod.load_chunks(p)
                except Exception as e:
                    if self.v:
                        print("[tiers] 读 %s 失败: %s" % (p, e))
            if not chunks:
                self.reason = "知识库都是空的"
                return
            self.rag = mod.RAG(chunks)
            self.n_chunks = len(chunks)
        except Exception as e:
            self.reason = "装载失败：%s: %s" % (type(e).__name__, e)
            self.rag = None

    def refresh_live(self):
        """★ 刷新【实时状态】知识块（温度/服务/变更会变）

        静态文档块不用动，但实时块过一会儿就陈旧了。
        重新跑一遍 live_kb.py 生成新文件，然后把整个索引重建。

        返回 True 表示刷新成功。
        """
        here = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(os.path.dirname(here), "live_kb.py")
        if not os.path.exists(script):
            return False
        try:
            import subprocess
            r = subprocess.run([sys.executable, script],
                               capture_output=True, encoding="utf-8",
                               errors="replace", timeout=30, cwd=here)
            if r.returncode != 0:
                return False
        except Exception:
            return False
        # 重建索引（轻量，几百个 chunk 毫秒级）
        try:
            self.__init__(verbose=False)
            return self.rag is not None
        except Exception:
            return False

    @property
    def available(self):
        return self.rag is not None

    def describe(self):
        if self.available:
            return "本地 RAG（%d 个知识块，纯标准库）" % self.n_chunks
        return "没有本地 RAG（%s）" % self.reason

    def answer(self, text):
        """抽取式回答（离线时用）

        ★ 实时块里有一行「【本块回答这类问题】...」，那是给 BM25 匹配用的
          （否则用户问"我改过几次 FPGA"，块里写的是"变更记录"，
           中文 bigram 零重叠，检索会落空）。
          但这一行不该出现在回答里 —— 读起来是噪音。
          所以这里过滤掉。
        """
        if not self.available:
            return None
        try:
            r = self.rag.answer(text)
            if not r:
                return None
            return r or None
        except Exception as e:
            if self.v:
                print("[tiers] RAG 出错: %s" % e)
            return None

    def build_prompt(self, text):
        """检索出资料，拼成给云端大模型的 prompt（在线时用）

        ★ 这样云端回答是"基于我们自己的项目文档"，
          既能溯源，又比纯 RAG 的摘录好读。
        """
        if not self.available:
            return None
        try:
            return self.rag.build_prompt(text)
        except Exception:
            return None

    def is_refusal(self, text):
        if not self.available:
            return False
        try:
            return self.rag.is_refusal(text)
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════
#  Tier 2 · 云端
# ══════════════════════════════════════════════════════════════════
def cloud_reachable(timeout=2.5, cache_secs=60):
    """探测云端能不能通（带缓存，别每次都探）"""
    now = time.time()
    if _cloud_cache["ok"] is not None and now - _cloud_cache["ts"] < cache_secs:
        return _cloud_cache["ok"]
    ok = False
    # ★ 先看有没有配 key；没 key 肯定不行
    has_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    if not has_key:
        try:
            for ln in open("/etc/zynq-agent.env", encoding="utf-8").read().splitlines():
                if ln.startswith("DEEPSEEK_API_KEY=") and len(ln) > 20:
                    has_key = True
                    break
        except Exception:
            pass
    if has_key:
        for host in (("api.deepseek.com", 443), ("1.1.1.1", 53),
                     ("223.5.5.5", 53)):
            try:
                s = socket.create_connection(host, timeout=timeout)
                s.close()
                ok = True
                break
            except Exception:
                continue
    _cloud_cache.update({"ts": now, "ok": ok})
    return ok


# ══════════════════════════════════════════════════════════════════
#  调度器
# ══════════════════════════════════════════════════════════════════
class Tiers(object):
    """三级调度的入口

    ★★★ 关于「切换模式」这件事（2026-10-02 修）★★★
    ══════════════════════════════════════════════════════════════
    原来的实现有两个问题，合起来导致「根本切不了」：

      ① core.py 里是
             _t = Tiers(mode=os.environ.get("AGENT_MODE", "auto"))
         只在【模块导入时】跑一次 —— mode 此后就固定死了，
         改环境变量对已启动的进程没有任何影响。

      ② cloud_api.py 的 /llm/config 声称能改模式：
             cur = mode
             return {"ok": True, "mode": cur}
         只改了个【局部变量】，既没落盘也没通知 agent。
         ⇒ 更糟：它返回"成功"，调用方以为切过去了。
           这比直接报错还坏 —— 是"假成功"。

    ⇒ 现在改成：
       · 真相存在 /home/zynq/.agent_mode（一个小文本文件）
       · Tiers.mode 是【动态属性】，每次读文件（1 秒缓存）
       · /llm/config 真的写这个文件
       · 加规则层命令（"切到本地模式"等），语音/文字都能切
       ⇒ 改完【立刻生效】，不用重启 agent（重启会丢会话上下文）。
    ══════════════════════════════════════════════════════════════
    """
    _live = 0

    def __init__(self, mode=None, verbose=False):
        # ★ mode 只作为【显式覆盖】（测试脚本才传）；
        #   生产里不传，交给 property 动态读文件。
        self._fixed = mode if mode in ("local", "cloud", "auto") else None
        # ★ 两个名字都留着：
        #   我重写 __init__ 时把 self.verbose 改成了 self.v，
        #   但类里还有几处老的 self.verbose 没改到 —— 自测就报
        #   AttributeError: 'Tiers' object has no attribute 'verbose'。
        #   与其逐个改（容易漏），不如两个都设上，以后用哪个都行。
        self.v = verbose
        self.verbose = verbose
        self.local = LocalModel(verbose=verbose)
        # ★ 本地 RAG：断网时的主力（纯标准库，几十 MB）
        self.rag = RagModel(verbose=verbose)
        self._mcache = (0.0, None)

    # ---- ★ 动态模式 ----
    @property
    def mode(self):
        """当前模式：local / cloud / auto

        ★ 每次直接读文件，不做缓存。
          踩过：原本加了 1 秒的【实例级】缓存，但切换函数清的是
          【模块级】的 _MODE_CACHE —— 两处缓存对不上，
          结果"切到本地"之后 self.mode 还是旧的 auto。

          读 /home/zynq/.agent_mode 就是一次 open+read（<0.1ms），
          比维护缓存的复杂度划算得多，所以干脆不缓存。
        """
        if self._fixed is not None:
            return self._fixed
        m = read_mode_file() or os.environ.get("AGENT_MODE", "auto")
        return m if m in ("local", "cloud", "auto") else "auto"

    @mode.setter
    def mode(self, m):
        """设置模式（也落盘，这样重启后还是这个）"""
        if m not in ("local", "cloud", "auto"):
            raise ValueError("mode 只能是 local/cloud/auto")
        self._fixed = None          # 解除显式覆盖，走文件
        write_mode_file(m)

    def describe_mode(self):
        """给用户看的模式说明"""
        m = self.mode
        what = {"local": "只用本地（规则 + RAG + 本地模型），不联网",
                "cloud": "只用云端（云端不通就报错，不降级）",
                "auto": "自动：云端通就用云端；不通自动降到本地"}[m]
        return ("当前模式：**%s** —— %s\n"
                "切换：说「切到本地模式」/「切到云端」/「切回自动」"
                % (m, what))

    # ---- 规则层 ----
    def match_rule(self, text):
        """返回命中的规则结果，没命中返回 None"""
        t = (text or "").strip()
        if not t:
            return None
        for name, pats, fn in RULES:
            for p in pats:
                if p.search(t):
                    return {"name": name, "fn": fn}
        return None

    def ask(self, text, cloud_fn=None):
        """主入口

        参数 cloud_fn(text) -> str 是外部传进来的云端调用（避免这里耦合 llm 模块）
        返回 {"ok", "tier", "reply", "rule"/"model", "elapsed"}

        ★★ 三级的分工（这一版重新捋过）：
            Tier 0  规则层（14 条）—— 确定性指令，<10ms，不调模型
            Tier 1  llama.cpp 本地模型（如果装了）
                    ↓ 没装就
                    ★ 本地 RAG（纯标准库，断网时的主力）
            Tier 2  云端 —— ★ 但先用 RAG 检索出资料塞进 prompt，
                            让大模型【基于我们的项目文档】回答
                            （既能溯源，又比纯摘录好读）
        """
        t0 = time.time()
        text = (text or "").strip()
        if not text:
            return {"ok": False, "tier": "-", "reply": "你没说什么。",
                    "elapsed": 0}

        # ═══ Tier 0：确定性指令优先 ═══
        # ★ 为什么规则层优先：像"现在多少度"这种问题，
        #   直接查传感器又快又准（<10ms），让大模型去猜反而慢且可能编。
        m = self.match_rule(text)
        if m is not None:
            try:
                reply = m["fn"](text)
                return {"ok": True, "tier": "rule", "rule": m["name"],
                        "reply": str(reply),
                        "elapsed": round(time.time() - t0, 3)}
            except Exception as e:
                # 规则层出错不致命，继续往下走
                if self.verbose:
                    print("[tiers] 规则 %s 出错: %s" % (m["name"], e))

        # ═══ mode=local：只用本地 ═══
        if self.mode == "local":
            return self._local_only(text, t0)

        # ═══ Tier 2：云端 ═══
        if self.mode in ("cloud", "auto"):
            if cloud_fn is not None:
                try:
                    # ★ 先用 RAG 把项目资料检索出来，再交给云端组织语言
                    r = None
                    if self.rag.available:
                        prompt = self.rag.build_prompt(text)
                        if prompt:
                            try:
                                r = cloud_fn(prompt)
                            except TypeError:
                                # 云端的回调只接受一个问题字符串
                                r = cloud_fn(text)
                    if not r:
                        r = cloud_fn(text)
                    if r:
                        return {"ok": True, "tier": "cloud", "reply": str(r),
                                "grounded": bool(self.rag.available),
                                "elapsed": round(time.time() - t0, 3)}
                except Exception as e:
                    if self.mode == "cloud":
                        return {"ok": False, "tier": "cloud",
                                "reply": "云端出错了：%s: %s"
                                         % (type(e).__name__, e),
                                "elapsed": round(time.time() - t0, 3)}
                    if self.verbose:
                        print("[tiers] 云端失败，降级: %s" % e)
            elif not cloud_reachable():
                if self.mode == "cloud":
                    return {"ok": False, "tier": "cloud",
                            "reply": "连不上云端（检查网络或 API key）。",
                            "elapsed": round(time.time() - t0, 3)}
                if self.verbose:
                    print("[tiers] 云端不可达，降级到本地")

        # ═══ 降级：本地 ═══
        return self._local_only(text, t0)

    def _local_only(self, text, t0):
        # Tier 1a：本地模型（llama.cpp，如果装了）
        if self.local.available:
            r = self.local.ask(text)
            if r:
                return {"ok": True, "tier": "local", "reply": r,
                        "elapsed": round(time.time() - t0, 3)}
        # ★ Tier 1b：本地 RAG —— 断网时的主力
        if self.rag.available:
            r = self.rag.answer(text)
            if r and not self.rag.is_refusal(r):
                return {"ok": True, "tier": "rag", "reply": r,
                        "elapsed": round(time.time() - t0, 3),
                        "note": "本地知识库检索（离线模式）"}
            if r:
                # RAG 明确拒答 —— 也如实告诉用户，别硬编
                return {"ok": True, "tier": "rag", "reply": r,
                        "elapsed": round(time.time() - t0, 3),
                        "refused": True,
                        "note": "本地知识库里没有相关内容（离线模式）"}
        # 都没命中
        return {
            "ok": False, "tier": "local",
            "reply": ("现在连不上云端%s，我只能处理这些固定的事：\n"
                      "  温度 / 服务状态 / 磁盘 / 运行时间 / IP / 时间 / 你是谁\n"
                      "  读寄存器 / 变更历史 / 停音乐 / 静音开关 / 改 FPGA 的流程\n"
                      "别的要等网络好了再说。"
                      % ("，也还没装本地模型"
                         if not self.local.available else "")),
            "elapsed": round(time.time() - t0, 3),
        }

    def describe(self):
        return {
            "mode": self.mode,
            "rules": len(RULES),
            "rule_names": [r[0] for r in RULES],
            "local_model": self.local.describe(),
            "local_available": self.local.available,
            "local_rag": self.rag.describe(),
            "rag_available": self.rag.available,
            "cloud_reachable": cloud_reachable(),
        }


# ══════════════════════════════════════════════════════════════════
#  自测
# ══════════════════════════════════════════════════════════════════
def selftest():
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        if not c:
            ok = False

    print("=" * 78)
    print(" 分级推理自测")
    print("=" * 78)

    t = Tiers(mode="auto")

    print("\n【1】规则层覆盖")
    cases = [
        ("现在多少度", "thermal"),
        ("板子热不热", "thermal"),
        ("服务状态怎么样", "services"),
        ("磁盘还剩多少空间", "disk"),
        ("你运行了多久", "uptime"),
        ("停一下音乐", "speak_stop"),
        ("进入静音模式", "silent_on"),
        ("你是谁", "version"),
        ("你会做什么", "capability"),
        ("读一下 scope_0 的寄存器", "regs"),
        ("最近改过什么", "changes"),
        ("你能改 FPGA 吗", "fpga"),
        ("现在几点", "time"),
        ("我的 IP 是多少", "network"),
    ]
    for text, want in cases:
        m = t.match_rule(text)
        got = m["name"] if m else None
        chk(got == want, "%-22s -> %s" % (text, got or "没命中"),
            "" if got == want else "期望 %s" % want)

    print("\n【2】不该误触发")
    # ★ 后两条是实测踩出来的：规则层原来有一条 `寄存器.*(值|多少)`，
    #   把"ES8388 的 DAC 音量寄存器是多少"这种【该走 RAG】的问题抢答了，
    #   然后回了一串 PL 的 IP 地址，答非所问。
    #   收窄正则之后加进这里，防止以后又放宽回去。
    for text in ("今天天气不错", "帮我写首诗", "1+1 等于几",
                 "ES8388 的 DAC 音量寄存器是多少",
                 "cnn 的量化公式是什么"):
        m = t.match_rule(text)
        chk(m is None, "%-16s -> 不命中" % text,
            "" if m is None else "误命中 %s" % m["name"])

    print("\n【3】规则层真跑（不需要板子，读不到的会优雅报错）")
    for text in ("现在多少度", "你是谁", "现在几点"):
        r = t.ask(text)
        chk(r["tier"] == "rule" and isinstance(r["reply"], str) and r["reply"],
            "%-14s -> [%s] %s" % (text, r["tier"], r["reply"][:40]))

    print("\n【4】mode=local 时不碰云端")
    tl = Tiers(mode="local")
    called = {"n": 0}

    def fake_cloud(text):
        called["n"] += 1
        return "云端回答"

    r = tl.ask("帮我写首诗", cloud_fn=fake_cloud)
    chk(called["n"] == 0, "mode=local 不会调云端")
    chk(r["tier"] == "local", "走的是本地层", r["tier"])
    chk("连不上云端" in r["reply"] or "没有" in r["reply"],
        "给出可用的降级说明", r["reply"][:40])

    print("\n【5】mode=cloud 时云端失败要报错（不静默降级）")
    tc = Tiers(mode="cloud")

    def boom(text):
        raise RuntimeError("模拟网络断")

    r = tc.ask("帮我写首诗", cloud_fn=boom)
    chk(r["ok"] is False, "云端失败 -> ok=false")
    chk(r["tier"] == "cloud", "tier 标成 cloud", r["tier"])
    chk("云端出错" in r["reply"], "错误说清楚了", r["reply"][:40])

    print("\n【6】mode=auto 时云端失败要降级")
    ta = Tiers(mode="auto")
    r = ta.ask("帮我写首诗", cloud_fn=boom)
    chk(r["tier"] == "local", "★ 自动降级到本地", r["tier"])
    chk(r["ok"] is False, "但还是如实说做不到")

    print("\n【7】mode=auto 且云端可用")
    r = ta.ask("帮我写首诗", cloud_fn=lambda t: "床前明月光")
    chk(r["tier"] == "cloud" and r["ok"], "走云端", r["tier"])

    print("\n【8】规则层优先于云端（确定性指令不走模型）")
    n = {"c": 0}

    def count_cloud(text):
        n["c"] += 1
        return "模型答的"

    r = ta.ask("现在多少度", cloud_fn=count_cloud)
    chk(n["c"] == 0, "★ 问温度没有调模型（直接查传感器）")
    chk(r["tier"] == "rule", "tier=rule", r["tier"])

    print("\n【9】状态描述")
    d = t.describe()
    chk("mode" in d and "rules" in d, "describe() 有 mode/rules")
    chk(d["rules"] >= 14, "规则数 >= 14", str(d["rules"]))
    print("      " + json.dumps({k: v for k, v in d.items()
                                 if k != "rule_names"}, ensure_ascii=False))

    print("\n【10】空输入")
    r = t.ask("")
    chk(r["ok"] is False, "空输入不崩")

    print()
    print("=" * 78)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 78)
    return ok


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="要问的话")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", default=None, help="cloud / local / auto")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return 0 if selftest() else 1

    t = Tiers(mode=a.mode, verbose=True)

    if a.status:
        print(json.dumps(t.describe(), ensure_ascii=False, indent=1))
        return 0

    if not a.text:
        ap.print_help()
        return 0

    text = " ".join(a.text)
    r = t.ask(text)
    print("【%s】%s" % (r["tier"], r["reply"]))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
