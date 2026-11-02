#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent.py —— Agent 内核：提示词 + 会话 + 工具循环 + 压缩 + 重复调用提醒

对应 DeepSeek Harness 的 `dsh-system-prompt` / `dsh-agent-loop` /
`dsh-session-persistence-jsonl` / `dsh-compaction` / `dsh-repeat-tool-reminder`。

★ 几条从 Harness 学来、**直接决定模型能不能干好活**的规则：

  1. **错误必须回灌给模型**，不能崩。工具报错就把它当成一条 tool 消息喂回去，
     模型会自己换个做法。这是"能自我纠错"的根源。
  2. **重复调用同一工具要提醒**。模型陷入循环是常见失败模式，
     检测到"和上一轮完全相同的调用"就在结果后面加一句提醒。
  3. **上下文要主动压缩**。不能等到爆掉；超阈值就丢掉最老的工具结果
     （只丢结果、保留对话骨架），并留一条"已省略"的说明。
  4. **轮数要有上限**。否则模型会绕圈烧 token。
"""
import json
import os
import time

from . import config
from . import llm
from . import spill
from . import tools as T
# ★ 硬件工具集：import 一下就会执行 @tool 装饰器，把那 14 个 hw_* 工具注册进
#   T.REGISTRY。不 import 的话工具是不会自己冒出来的
#   （踩过：部署完发现工具数还是 12，硬件工具 0 个）。
from . import hw_tools  # noqa: F401

# ══════════════════════════════════════════════════════════════════════
#  ★★★ 静音模式提示块 —— 必须【动态生成】（2026-10-03 修）
# ══════════════════════════════════════════════════════════════════════
# 用户报："为什么明明已经关掉静音模式，模型还要问是否关掉静音"
#
# 根因：这几行原来是【硬编码】在 SYSTEM 提示词里的死指令：
#       "【重要 · 静音模式】用户明确要求：在他本人同意之前，不许发出任何声音…"
#       它跟 /etc/zynq-silent 这个锁文件【完全无关】。
#       ⇒ 锁文件早就不存在了，模型却还是照着提示词拒绝出声，
#         甚至会先自己去 ls 一下、发现文件不在，然后依然说"我不能出声"。
#         （实测原话："/etc/zynq-silent 这个锁文件其实不存在…纯粹是我按你的
#           要求闭嘴"—— 它自己都矛盾了，因为指令是死的。）
#
# 修法：把这段抽成 {silent_block}，运行时按锁文件是否真的存在来决定填什么：
#   · 锁在   -> 注入禁止出声的强约束（和原来一样）
#   · 锁不在 -> 注入一句"现在可以正常出声"的明确许可，
#              免得模型凭历史/印象继续自我审查
# ★ 也顺带把"该不该出声"的唯一依据统一到 SILENT_FLAG 上，
#   和 tools.py / policy.py / hw_tools.py 的判断保持一致。
# ══════════════════════════════════════════════════════════════════════
SILENT_FLAG = "/etc/zynq-silent"

SILENT_ON_BLOCK = """
【重要 · 静音模式（当前生效中）】用户要求在他本人明确同意之前不许发出任何声音。
- 不要调用 speak 工具，也不要用 audio 工具放音。
- 不要用 shell 启动 zynq-audio 服务，也不要绕过 /etc/zynq-silent。
- 如果用户要求你说话，就告诉他现在处于静音模式，请他明确同意后再放开。
麦克风录音不受限制，可以正常用。
"""

SILENT_OFF_BLOCK = """
【声音状态：正常】当前【不在】静音模式（/etc/zynq-silent 不存在），
你可以正常用 speak / audio 工具出声，不需要再征求同意。
★ 不要因为历史对话里提到过静音就继续自我审查 —— 判断依据只有那个锁文件。
"""


def silent_locked():
    """静音锁是否生效（唯一判据：锁文件在不在）"""
    return os.path.exists(SILENT_FLAG)

SYSTEM = """你叫「系统管家小白」——运行在一块正点原子领航者 ZYNQ7020 开发板上的自主助手。
别人问你是谁 / 你叫什么，就答"我是系统管家小白，这块板子的系统管家"。
{silent_block}
你不是聊天机器人：**你有一双手**（工具），可以真的去操作这台设备并把事情做完。
你还能**听见和说话**：
- 想"说出来"就用 `speak` 工具 —— 它会真的从板载喇叭放出来，用户听得见。
  回答用户、汇报结果、打招呼都优先用 `speak`（内容要口语化、简短，
  不要念 markdown/代码/表格；技术细节留在文字回复里）。
- 想"听"就用 `listen` 工具 —— 它会开麦克风录几秒并识别成文字。
- 想验证喇叭/麦克风是否正常，用 `audio` 工具的 `selftest`。
- **你的嘴和耳朵是同一套硬件**，所以说话时听不见、听的时候别说话（半双工）。

## 你在哪
- 硬件：Xilinx Zynq-7020（双核 Cortex-A9 667MHz + FPGA），1024x600 RGB LCD 触摸屏
- 系统：Ubuntu 20.04（armv7l），内核 5.4.0-xilinx-v2020.2
- 这台设备上还有一个自研的 FPGA 桌面（卡片首页 / 小说 / 浏览器 / 示波器 / GPU 测试台）
- 工作目录：{workdir}
- 当前时间：{now}

## 怎么干活
1. **先看再动**。要改文件先用 read 看清内容，要查状态先跑命令，**不要凭印象猜**。
2. **用工具，不要编造**。你没有"记忆里的系统状态"——需要什么就去查。
   凡是涉及具体数值（CPU、内存、温度、文件大小、路径）的结论，必须来自工具输出。
3. **做事要有验证**。改完东西要再读一次/再跑一次确认，别假设成功。
4. **出错就换法子**。工具返回的错误信息是给你的线索，不是终点。
5. **长输出看摘要**。工具结果如果很长，会只给你开头+结尾和一个文件路径，
   需要细节就用 read/grep 去看那个文件，不要重复请求同一个大输出。
6. **危险操作会被拒**。删除、覆盖系统文件这类命令会被安全策略拦下并告诉你原因，
   这时要换一个不改动系统的做法，或先向用户说明为什么必须这么做。
7. **简洁**。回答用中文，直接给结论和证据；不要复述工具输出，不要客套。

## 工具
{toollist}
"""


class Session(object):
    """会话落盘（jsonl）。对应 dsh-session-persistence-jsonl。"""

    def __init__(self, name=None, cfg=None, persist=True):
        cfg = cfg or config.load()
        self.dir = cfg["session_dir"]
        os.makedirs(self.dir, exist_ok=True)
        self.name = name or time.strftime("s%m%d_%H%M%S")
        self.path = os.path.join(self.dir, self.name + ".jsonl")
        self.persist = persist
        self.messages = []
        if persist and os.path.exists(self.path):
            try:
                for ln in open(self.path, encoding="utf-8"):
                    ln = ln.strip()
                    if ln:
                        self.messages.append(json.loads(ln))
            except Exception:
                pass

    def add(self, m):
        self.messages.append(m)
        if self.persist:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return m

    def history(self, n=None):
        """取历史（不含 system）。压缩过的那条 summary 永远带上。"""
        h = [m for m in self.messages if m.get("role") != "system"]
        if n:
            h = h[-n:]
        return h


class Agent(object):
    def __init__(self, cfg=None, session=None, on_event=None, verbose=True):
        self.cfg = cfg or config.load()
        self.session = session or Session(cfg=self.cfg)
        self.on_event = on_event or (lambda k, **kw: None)
        self.verbose = verbose
        self.ctx = {"approved": False, "todo": []}

    # ---------------- 提示词 ----------------
    def system_prompt(self):
        tl = []
        for n, t in T.REGISTRY.items():
            tl.append("- `%s`：%s" % (n, t["desc"].split("\n")[0]))
        # ★ 静音块按【锁文件当前状态】动态填 —— 不要写死（见文件头说明）
        return SYSTEM.format(workdir=self.cfg["workdir"],
                             now=time.strftime("%Y-%m-%d %H:%M:%S"),
                             toollist="\n".join(tl),
                             silent_block=(SILENT_ON_BLOCK if silent_locked()
                                           else SILENT_OFF_BLOCK))

    # ---------------- 压缩 ----------------
    def maybe_compact(self, messages):
        """超过阈值就把【老的工具结果】裁掉。对应 dsh-compaction-tool-result-pruner。"""
        n = spill.context_chars(messages)
        if n < self.cfg["context_chars"]:
            return messages, False
        keep = self.cfg["keep_recent_rounds"] * 2
        head, tail = messages[:1], messages[-keep:]
        mid = messages[1:-keep] if len(messages) > keep + 1 else []
        dropped = 0
        for m in mid:
            if m.get("role") == "tool" and len(str(m.get("content") or "")) > 400:
                m["content"] = ("[旧工具结果已省略以省上下文（%d 字符）]"
                                % len(str(m.get("content"))))
                dropped += 1
        out = head + mid + tail
        if dropped:
            self.log("压缩：裁掉 %d 条旧工具结果（原 %d 字符）" % (dropped, n))
        return out, dropped > 0

    # ---------------- 主循环 ----------------
    def run(self, task, max_rounds=None, system=None, use_tools=True):
        """跑一个任务。

        system / use_tools 是给「外部前端」用的（ESP32 语音那个场景）：
        前端可以自带一套提示词（比如要求只回 JSON），并且关掉工具，
        这样它就退化成一次"有板载 Agent 兜底"的模型调用 ——
        换提示词不用重烧固件，API key 也不落到设备上。

        ★★★ 2026-10-02 加了分级推理（见 agent/tiers.py）：
          进主循环【之前】先过一遍规则层。像"现在多少度""你是谁"
          这种确定性指令直接答，不走模型 —— 快、准、而且断网也能用。
          只有规则层没命中，才进后面的模型循环。
          这样"断网就废"这个毛病就有了兜底。
        """
        cfg = self.cfg
        mr = int(max_rounds or cfg["max_rounds"])

        # ---- ★ 分级推理：规则层先试 ----
        if use_tools:
            try:
                from . import tiers as _tiers
                # ★★ 不要传 mode=...
                #
                # 踩过：原来是
                #     _t = _tiers.Tiers(mode=os.environ.get("AGENT_MODE", "auto"))
                # 看起来很合理，但 Tiers 构造后每次调用都【新建一个实例】，
                # 传了 mode 就等于把模式钉死成构造那一刻的环境变量 ——
                # 之后无论改环境变量还是改模式文件都不会生效。
                # 不传的话，Tiers.mode 是动态属性，每次读 /home/zynq/.agent_mode，
                # 所以「切到本地模式」这类指令改完立刻生效。
                _t = _tiers.Tiers()
                _m = _t.match_rule(task)
                if _m is not None:
                    try:
                        _reply = _m["fn"](task)
                        self.session.add({"role": "user", "content": task})
                        self.session.add({"role": "assistant",
                                          "content": str(_reply)})
                        self.log("规则层命中 %s（不走模型）" % _m["name"])
                        self.on_event("assistant", text=str(_reply)[:200],
                                      elapsed=0.0)
                        return str(_reply), {"rounds": 0, "tier": "rule",
                                             "rule": _m["name"]}
                    except Exception as _e:
                        self.log("规则 %s 出错，回退到模型：%s"
                                 % (_m["name"], _e))
            except Exception as _e:
                self.log("分级推理加载失败（不影响主流程）：%s" % _e)

        self.session.add({"role": "user", "content": task})
        messages = [{"role": "system", "content": system or self.system_prompt()}] \
            + self.session.history()
        prev_sig = None
        t_start = time.time()

        for rnd in range(1, mr + 1):
            self.on_event("round", n=rnd, total=mr)
            try:
                msg = llm.chat(messages,
                               tools=(T.schemas() if use_tools else None),
                               cfg=cfg)
            except llm.LLMError as e:
                self.log("LLM 出错：%s" % e)
                return "（模型调用失败：%s）" % e, {"rounds": rnd, "err": str(e)}

            u = msg.get("_usage") or {}
            self.on_event("assistant", text=(msg.get("content") or "")[:200],
                          usage=u, elapsed=msg.get("_elapsed"))
            calls = msg.get("tool_calls") or []
            clean = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                clean["tool_calls"] = calls
            self.session.add(clean)
            messages.append(clean)

            if not calls:
                ans = msg.get("content") or ""
                self.log("完成（%d 轮，%.1fs）" % (rnd, time.time() - t_start))
                return ans, {"rounds": rnd, "usage": u}

            if not use_tools:
                # 关掉工具时模型不该给 tool_calls，真给了也不能执行
                self.log("（工具已关闭，忽略 %d 个 tool_call）" % len(calls))
                return (msg.get("content") or ""), {"rounds": rnd, "usage": u}

            for tc in calls:
                fn = (tc.get("function") or {})
                name, args = fn.get("name"), fn.get("arguments")
                self.on_event("tool", name=name, args=args)
                self.log("→ %s(%s)" % (name, (str(args) or "")[:120]))
                result = T.call(name, args, self.ctx)

                # ★ 重复调用提醒（dsh-repeat-tool-reminder）
                sig = "%s|%s" % (name, args)
                if sig == prev_sig:
                    result += ("\n\n[提醒] 你刚用完全一样的参数调过一次 %s。"
                               "如果结果没变，别再重复 —— 换个思路，"
                               "或者把你的结论告诉用户。" % name)
                prev_sig = sig

                self.log("← %d 字符" % len(result))
                self.on_event("result", name=name, text=result[:200])
                tm = {"role": "tool", "tool_call_id": tc.get("id") or name,
                      "content": result}
                self.session.add(tm)
                messages.append(tm)

            messages, _ = self.maybe_compact(messages)

        return ("（达到最大轮数 %d 还没做完。把已完成的和你卡在哪告诉用户。）" % mr,
                {"rounds": mr, "timeout": True})

    def log(self, s):
        if self.verbose:
            print("[agent] " + s)
