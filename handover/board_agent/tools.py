#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools.py —— 工具注册表与实现

对应 DeepSeek Harness 的 `dsh-tools` + `dsh-tool-fs` + `dsh-tool-pwsh` +
`dsh-tool-fs-search` + `dsh-tool-web` + `dsh-tool-todo`。

设计原则（照抄 Harness）：
  1. **工具正交**：一个工具只干一件事。没有"万能 bash"包打天下 ——
     模型需要读文件就调 read，不需要自己拼 `cat`。
  2. **结果统一走输出治理**（spill.govern）：长输出落盘 + 只回摘要。
  3. **错误也回灌**：工具抛异常 → 变成一条结构化错误消息给模型，
     而不是让整个 Agent 崩掉。这是"能自我纠错"的关键。
  4. **参数校验在前**：参数不对直接回明确原因，别让模型猜。
"""
import glob as _glob
import json
import os
import re
import subprocess
import time
import urllib.request

from . import config
from . import guard
from . import spill
from . import policy

# ---------------------------------------------------------------- 工具表
REGISTRY = {}


# ══════════════════════════════════════════════════════════════════
#  ★ 静音锁（2026-09-28 事故后加）
#  用户明确要求"在我同意之前不许出声"。但 Agent 用 shell 工具
#  把音频服务拉起来放过音，绕过了这个要求。所以在这里硬拦。
# ══════════════════════════════════════════════════════════════════
SILENT_FLAG = "/etc/zynq-silent"
SILENT_MSG = (
    "【静音锁生效】用户要求在他本人明确同意前不许发出任何声音。"
    "已拒绝本次放音/音频硬件操作。"
    "如果你认为必须出声，请在回答里向用户说明并请他确认，"
    "不要尝试启动 zynq-audio 服务或绕过这个限制。"
)


def silent_locked():
    """静音锁是否生效"""
    return os.path.exists(SILENT_FLAG)




def tool(name, desc, params):
    def deco(fn):
        REGISTRY[name] = {"name": name, "desc": desc, "params": params, "fn": fn}
        return fn
    return deco




# ══════════════════════════════════════════════════════════════════
#  权限闸门（2026-09-28 事故后加）
#
#  事故回顾：用户说"不要再播放了"，Agent 自己用 shell 把音频服务拉起来
#  放音 —— 两次。根因是 Agent 有不受限的 root shell 且没有"该不该做"概念。
#
#  现在所有 shell/write/edit 都先过 policy.classify_*：
#      allow   直跑
#      deny    拒绝并说明原因
#      confirm 登记待批准，返回给模型让它问用户
# ══════════════════════════════════════════════════════════════════
def _policy_gate(kind, payload):
    """返回 None 表示放行；返回字符串表示要中止并把这句话回给模型"""
    try:
        if kind == "shell":
            dec, why = policy.classify_shell(payload)
        else:
            dec, why = policy.classify_write(payload)
    except Exception as e:
        return "【权限层异常】%s —— 为安全起见拒绝执行" % e

    if dec == "allow":
        return None
    if policy.is_approved(kind, payload):
        return None

    if dec == "deny":
        return "【权限层拒绝】%s\n（要改这条规则：编辑 %s）" % (
            why, policy.POLICY_FILE)

    rid = policy.request(kind, payload, why)
    return ("【需要用户批准】%s\n"
            "已登记为待批准动作 id=%s。请告诉用户你想做什么、为什么，"
            "请他在界面上点「同意」或「拒绝」。**不要自己绕过。**"
            % (why, rid))


def schemas(enabled=None):
    """给 LLM 的 tools 参数（DeepSeek 用 OpenAI 格式）"""
    out = []
    for n, t in REGISTRY.items():
        if enabled and n not in enabled:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": n,
                "description": t["desc"],
                "parameters": t["params"],
            },
        })
    return out


def call(name, args, ctx=None):
    """执行一个工具。**永远返回字符串**（异常也变字符串）"""
    t = REGISTRY.get(name)
    if not t:
        return "错误：没有这个工具 '%s'。可用：%s" % (name, ", ".join(REGISTRY))
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except Exception as e:
            return "错误：参数不是合法 JSON（%s）。你给的是：%s" % (e, args[:200])
    try:
        r = t["fn"](args or {}, ctx or {})
    except Exception as e:
        import traceback
        return "工具 '%s' 执行出错：%s: %s\n%s" % (
            name, type(e).__name__, e, traceback.format_exc()[-800:])
    return spill.govern(name, r)[0]


# ---------------------------------------------------------------- shell
@tool("shell", "在本机执行一条 shell 命令，返回 stdout+stderr。"
               "有超时；输出过长会自动落盘只回摘要。"
               "不允许销毁性命令（rm -rf / 之类会被拒绝）。",
      {"type": "object",
       "properties": {
           "cmd": {"type": "string", "description": "要执行的命令"},
           "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
       },
       "required": ["cmd"]})
def _shell(a, ctx):
    _g = _policy_gate("shell", a.get("cmd", ""))
    if _g:
        return _g
    cfg = config.load()
    cmd = a.get("cmd", "")
    v = guard.check(cmd, cfg, approved=bool(ctx.get("approved")))
    if not v.allow:
        return "[被安全策略拦住 · %s] %s\n（换一种不会改动系统的做法，或先说明为什么需要这么做）" \
               % (v.level, v.why)
    to = int(a.get("timeout") or cfg["tool_timeout"])
    to = max(1, min(to, 600))
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, cwd=cfg["workdir"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=to)
        out = (p.stdout or b"").decode("utf-8", "replace")
        rc = p.returncode
        head = "$ %s\n(exit=%d, %.2fs)" % (cmd, rc, time.time() - t0)
        return head + "\n" + (out if out.strip() else "(无输出)")
    except subprocess.TimeoutExpired:
        return "$ %s\n[超时 %d 秒被中止] 换个更快/更窄的命令再试" % (cmd, to)


# ---------------------------------------------------------------- 文件
@tool("read", "读一个文本文件（带行号）。大文件用 offset/limit 分段读。",
      {"type": "object",
       "properties": {
           "path": {"type": "string"},
           "offset": {"type": "integer", "description": "从第几行开始（1 起）"},
           "limit": {"type": "integer", "description": "读多少行，默认 400"},
       },
       "required": ["path"]})
def _read(a, ctx):
    p = os.path.expanduser(a.get("path", ""))
    v = guard.check_path(p, write=False)
    if not v.allow:
        return "[被安全策略拦住] " + v.why
    if not os.path.isfile(p):
        cand = _glob.glob(p)
        return "错误：文件不存在 %s%s" % (p, ("；相近的有：%s" % cand[:5]) if cand else "")
    off = max(1, int(a.get("offset") or 1))
    lim = max(1, min(int(a.get("limit") or 400), 4000))
    out = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, ln in enumerate(f, 1):
                if i < off:
                    continue
                if i >= off + lim:
                    break
                out.append("%5d| %s" % (i, ln.rstrip("\n")))
    except Exception as e:
        return "读取失败：%s" % e
    if not out:
        return "(文件为空或 offset 超出范围)"
    return "\n".join(out)


@tool("write", "写文件（覆盖）。父目录不存在会自动建。",
      {"type": "object",
       "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
       "required": ["path", "content"]})
def _write(a, ctx):
    _g = _policy_gate("write", a.get("path", ""))
    if _g:
        return _g
    p = os.path.expanduser(a.get("path", ""))
    v = guard.check_path(p, write=True)
    if not v.allow:
        return "[被安全策略拦住] " + v.why
    try:
        os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(a.get("content", ""))
        return "已写入 %s（%d 字节）" % (p, len(a.get("content", "")))
    except Exception as e:
        return "写入失败：%s" % e


@tool("edit", "在文件里做一次精确字符串替换（old 必须唯一出现）。",
      {"type": "object",
       "properties": {"path": {"type": "string"}, "old": {"type": "string"},
                      "new": {"type": "string"}},
       "required": ["path", "old", "new"]})
def _edit(a, ctx):
    _g = _policy_gate("write", a.get("path", ""))
    if _g:
        return _g
    p = os.path.expanduser(a.get("path", ""))
    v = guard.check_path(p, write=True)
    if not v.allow:
        return "[被安全策略拦住] " + v.why
    try:
        s = open(p, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return "读不到文件：%s" % e
    old, new = a.get("old", ""), a.get("new", "")
    n = s.count(old)
    if n == 0:
        return "没找到那段文本。注意要逐字匹配（含空格/缩进）。"
    if n > 1:
        return "那段文本出现了 %d 次，不唯一。多给点上下文让它唯一。" % n
    try:
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        return "已修改 %s" % p
    except Exception as e:
        return "写入失败：%s" % e


@tool("glob", "按通配符找文件（比如 '**/*.py'）。返回路径列表。",
      {"type": "object",
       "properties": {"pattern": {"type": "string"},
                      "root": {"type": "string", "description": "起始目录"}},
       "required": ["pattern"]})
def _glob_tool(a, ctx):
    cfg = config.load()
    root = os.path.expanduser(a.get("root") or cfg["workdir"])
    pat = a.get("pattern", "*")
    full = pat if os.path.isabs(pat) else os.path.join(root, pat)
    hits = _glob.glob(full, recursive=True)
    hits = [h for h in hits if os.path.isfile(h)]
    if not hits:
        return "没找到匹配 %s 的文件" % pat
    return "找到 %d 个：\n%s" % (len(hits), "\n".join(sorted(hits)[:200]))


@tool("grep", "在文件里搜正则，返回匹配行（带文件名和行号）。",
      {"type": "object",
       "properties": {"pattern": {"type": "string"},
                      "root": {"type": "string"},
                      "include": {"type": "string",
                                  "description": "只搜匹配这个通配的文件，如 '*.py'"}},
       "required": ["pattern"]})
def _grep(a, ctx):
    cfg = config.load()
    root = os.path.expanduser(a.get("root") or cfg["workdir"])
    pat = a.get("pattern", "")
    inc = a.get("include") or "*"
    try:
        rx = re.compile(pat)
    except Exception as e:
        return "正则不合法：%s" % e
    out, n = [], 0
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if not d.startswith(".") and d != "__pycache__"]
        for f in fs:
            if inc != "*" and not _glob.fnmatch.fnmatch(f, inc):
                continue
            fp = os.path.join(r, f)
            try:
                if os.path.getsize(fp) > 4 * 1024 * 1024:
                    continue
                for i, ln in enumerate(open(fp, encoding="utf-8",
                                            errors="replace"), 1):
                    if rx.search(ln):
                        out.append("%s:%d: %s" % (fp, i, ln.rstrip()[:200]))
                        n += 1
                        if n > 400:
                            return "\n".join(out) + "\n…（截断，超过 400 条）"
            except Exception:
                continue
    return "\n".join(out) if out else "没有匹配"


# ---------------------------------------------------------------- 网络
@tool("http", "抓一个网页/接口，返回正文（截断+落盘）。支持 http 和 https。",
      {"type": "object",
       "properties": {"url": {"type": "string"},
                      "max_kb": {"type": "integer", "description": "最多取多少 KB"}},
       "required": ["url"]})
def _http(a, ctx):
    url = a.get("url", "")
    kb = max(4, min(int(a.get("max_kb") or 200), 2048))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux armv7l) agent/1.0"})
        # 板子上系统 CA 用不了，https 降级为不校验（和浏览器同一策略）
        import ssl
        try:
            ctxs = ssl.create_default_context()
            data = urllib.request.urlopen(req, timeout=20, context=ctxs).read(kb * 1024)
        except Exception:
            ctxs = ssl._create_unverified_context()
            data = urllib.request.urlopen(req, timeout=20, context=ctxs).read(kb * 1024)
        return data.decode("utf-8", "replace")
    except Exception as e:
        return "抓取失败：%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------- 任务列表
@tool("todo", "维护本次任务的任务列表。传 items 就覆盖写入（每条 '状态|内容'，"
              "状态是 todo/doing/done）。不传就只读当前列表。",
      {"type": "object",
       "properties": {"items": {"type": "array", "items": {"type": "string"}}},
       "required": []})
def _todo(a, ctx):
    store = ctx.setdefault("todo", [])
    if "items" in a and a["items"] is not None:
        store[:] = list(a["items"])
    if not store:
        return "（任务列表为空）"
    return "\n".join("- " + str(x) for x in store)


# ---------------------------------------------------------------- 系统信息
@tool("system", "一眼看板载系统状态：CPU/内存/磁盘/温度/网络/负载。"
                "需要汇报系统情况时用它，不要自己拼一堆命令。",
      {"type": "object", "properties": {}, "required": []})
def _system(a, ctx):
    cfg = config.load()
    out = []
    v = _shell({"cmd": "uptime; echo ---; free -m | head -3; echo ---; "
                       "df -h / | tail -1; echo ---; "
                       "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null; "
                       "cat /proc/loadavg"}, {})
    out.append(v)
    # 网络
    try:
        r = subprocess.run("ip -br addr show | grep -v '^lo'",
                           shell=True, stdout=subprocess.PIPE, timeout=5)
        out.append("--- 网络 ---\n" + r.stdout.decode("utf-8", "replace"))
    except Exception:
        pass
    # 温度（Zynq 走 hwmon）
    try:
        for g in _glob.glob("/sys/class/hwmon/hwmon*/temp1_input"):
            t = int(open(g).read().strip())
            out.append("--- 温度 ---\n%.1f C" % (t / 1000.0))
            break
    except Exception:
        pass
    return "\n".join(out)


# ---------------------------------------------------------------- 音频（嘴和耳朵）
# 硬件是独占资源，一律走板载音频服务 (127.0.0.1:8767, ui/audio_svc.py)
@tool("speak", "**用板载喇叭说出**一段中文。这是你'说话'的唯一方式。"
               "回答用户、汇报结果、打招呼都用它。文字要口语化、简短，"
               "别把 markdown、代码、表格念出来。",
      {"type": "object",
       "properties": {
           "text": {"type": "string", "description": "要说出来的中文（≤900 字）"},
           "per": {"type": "integer",
                   "description": "音色：0=女声(默认) 1=男声 3=度逍遥 4=度丫丫"},
       },
       "required": ["text"]})
def _speak(a, ctx):
    if silent_locked():
        return SILENT_MSG
    from . import tts
    text = (a.get("text") or "").strip()
    if not text:
        return "错误：text 是空的，没东西可说。"
    try:
        p, secs = tts.speak(text, per=int(a.get("per") or 0))
        return "已用喇叭播放 %.1f 秒：%s" % (secs, text[:120])
    except Exception as e:
        return "说话失败：%s: %s\n（检查音频服务：python3 -m agent.audio_client）" \
               % (type(e).__name__, e)


@tool("listen", "**用板载麦克风听**几秒并识别成文字。用户说'听我说''你听到了吗'"
                "或者需要语音输入时用它。",
      {"type": "object",
       "properties": {
           "secs": {"type": "number", "description": "录多久，默认 4 秒"},
       },
       "required": []})
def _listen(a, ctx):
    from . import tts
    secs = float(a.get("secs") or 4.0)
    secs = max(1.0, min(secs, 20.0))
    try:
        text, p = tts.listen(secs=secs)
        if not text:
            return "录了 %.1f 秒，但没听清内容（录音在 %s，可以自己分析）" % (secs, p)
        return "听到用户说：「%s」" % text
    except Exception as e:
        return "听写失败：%s: %s" % (type(e).__name__, e)


@tool("audio", "音频硬件操作：自检 / 放指定单音 / 调音量 / 看状态。"
               "用来验证喇叭和麦克风是否正常。",
      {"type": "object",
       "properties": {
           "action": {"type": "string",
                      "enum": ["selftest", "tone", "volume", "state"],
                      "description": "selftest=放音同时录音自检; tone=放单音; "
                                     "volume=设音量; state=看状态"},
           "freq": {"type": "number", "description": "单音频率，默认 1000"},
           "secs": {"type": "number", "description": "单音时长，默认 1"},
           "v": {"type": "integer", "description": "音量 0..33"},
       },
       "required": ["action"]})
def _audio(a, ctx):
    if silent_locked():
        return SILENT_MSG
    from . import audio_client as ac
    act = (a.get("action") or "state").lower()
    if not ac.alive():
        return "音频服务没在跑（127.0.0.1:8767）。启动：\n" \
               "  sudo pkill -f audio_svc.py; cd /home/zynq/ui && " \
               "sudo setsid nohup python3 -u audio_svc.py > /tmp/audio_svc.log 2>&1 &"
    try:
        if act == "selftest":
            d = ac.selftest(float(a.get("freq") or 1000), float(a.get("secs") or 1.2))
            return ("自检：%s\n@%.0fHz 静音 %.1f -> 放音 %.1f (%.1f dB)\n%s"
                    % (d.get("verdict"), d.get("freq", 1000),
                       d.get("goe_quiet", 0), d.get("goe_tone", 0),
                       d.get("ratio_db", 0),
                       json.dumps(d.get("per_channel", {}), ensure_ascii=False)))
        if act == "tone":
            r = ac.play_tone(float(a.get("freq") or 1000),
                             float(a.get("secs") or 1.0))
            return "已放 %.2f 秒的单音" % r.get("secs", 0)
        if act == "volume":
            r = ac.volume(int(a.get("v") if a.get("v") is not None else 30))
            return "音量已设为 %d（0..33）" % r.get("volume", 0)
        return json.dumps(ac.state(), ensure_ascii=False, indent=2)
    except Exception as e:
        return "音频操作失败：%s: %s" % (type(e).__name__, e)
