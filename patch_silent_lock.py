#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_silent_lock.py —— 给 Agent 的放音能力上锁

事故（2026-09-28）：
  用户明确说"不要再播放了"。我停了音频服务。
  但 Agent 自己用 shell 工具把服务拉起来、做了自检、还从喇叭放了自我介绍 ——
  用户的要求被绕过了。

根因：Agent 有不受限的 shell 工具，而 speak/audio 工具没有"静音"概念。

修法（两层）：
  1) tools.py 里 speak / audio 两个工具**先检查 /etc/zynq-silent**，
     存在就直接返回"静音锁生效，拒绝放音"，不执行任何硬件动作。
  2) core.py 的 system 提示里明确告诉模型：现在处于静音模式，
     不要尝试启动音频服务或绕过它。
"""
import io
import re
import sys

# ══════════════════════════════ 1) tools.py 加守卫
P1 = "agent/tools.py"
s1 = io.open(P1, encoding="utf-8").read()

if "SILENT_FLAG" in s1:
    print("tools.py 已打过补丁")
else:
    guard = '''

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

'''
    # 插在 REGISTRY = {} 之后
    s1 = s1.replace("REGISTRY = {}", "REGISTRY = {}\n" + guard, 1)
    print("  OK: 加了 silent_locked() 守卫")

# ---- 给 speak 工具加守卫 ----
m = re.search(r'@tool\(\s*"speak"(.*?)\ndef\s+(\w+)\(', s1, re.S)
if m:
    fn = m.group(2)
    # 在函数体第一行插入检查
    pat = re.compile(r"(def\s+%s\([^)]*\):\s*\n)" % re.escape(fn))
    ins = (r"\1"
           "    if silent_locked():\n"
           "        return SILENT_MSG\n")
    s1n, n = pat.subn(ins, s1, count=1)
    if n:
        s1 = s1n
        print("  OK: speak 工具已加静音锁")
    else:
        print("  [!] speak 函数体没匹配到")
else:
    print("  [!] 没找到 speak 工具定义")

# ---- 给 audio 工具加守卫 ----
m2 = re.search(r'@tool\(\s*"audio"(.*?)\ndef\s+(\w+)\(', s1, re.S)
if m2:
    fn2 = m2.group(2)
    pat2 = re.compile(r"(def\s+%s\([^)]*\):\s*\n)" % re.escape(fn2))
    ins2 = (r"\1"
            "    if silent_locked():\n"
            "        return SILENT_MSG\n")
    s1n, n2 = pat2.subn(ins2, s1, count=1)
    if n2:
        s1 = s1n
        print("  OK: audio 工具已加静音锁")
    else:
        print("  [!] audio 函数体没匹配到")
else:
    print("  [!] 没找到 audio 工具定义")

io.open(P1, "w", encoding="utf-8").write(s1)
import ast
ast.parse(io.open(P1, encoding="utf-8").read())
print("  tools.py syntax OK")

# ══════════════════════════════ 2) core.py 的 system 提示
P2 = "agent/core.py"
s2 = io.open(P2, encoding="utf-8").read()
if "静音锁" in s2:
    print("core.py 已提过静音锁")
else:
    # 找 SYSTEM 提示串，往里加一段
    anchor = "SYSTEM"
    idx = s2.find(anchor)
    if idx == -1:
        print("  [!] 没找到 SYSTEM 提示，跳过")
    else:
        note = (
            "\\n\\n【重要 · 静音模式】用户明确要求：在他本人同意之前，"
            "不许发出任何声音。\\n"
            "- 不要调用 speak 工具，也不要用 audio 工具放音。\\n"
            "- 不要用 shell 启动 zynq-audio 服务，也不要绕过 /etc/zynq-silent。\\n"
            "- 如果用户要求你说话，就告诉他现在处于静音模式，"
            "请他明确同意后再放开。\\n"
            "麦克风录音不受限制，可以正常用。"
        )
        # 在 SYSTEM 串的结尾引号前插入
        m3 = re.search(r'(SYSTEM\s*=\s*(?:"""|\'\'\'|"))(.*?)((?:"""|\'\'\'|"))',
                       s2, re.S)
        if m3:
            s2 = s2[:m3.end(2)] + note + s2[m3.end(2):]
            io.open(P2, "w", encoding="utf-8").write(s2)
            import ast as _a
            _a.parse(io.open(P2, encoding="utf-8").read())
            print("  OK: system 提示已加静音模式说明, syntax OK")
        else:
            print("  [!] SYSTEM 串格式没匹配到，跳过")
