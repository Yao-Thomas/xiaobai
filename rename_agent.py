#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 "系统管家小白" 这个名字贯到 agent 代码 / 服务 / 桌面上"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AG = os.path.join(HERE, "agent")
UI = os.path.join(HERE, "ui")

REPL = [
    (os.path.join(AG, "zynq-agent.service"),
     [("Description=Onboard Agent (Zynq local agent, DeepSeek-backed)",
       "Description=系统管家小白 (Zynq onboard agent, DeepSeek-backed)")]),
    (os.path.join(AG, "main.py"),
     [('server_version = "ZynqAgent/0.1"',
       'server_version = "XiaoBai/0.1"'),
      ('print(" 板载 Agent HTTP 服务")',
       'print(" 系统管家小白 · HTTP 服务")'),
      ('print("板载 Agent 交互模式（Ctrl-C 退出；输入 exit 结束）")',
       'print("系统管家小白 · 交互模式（Ctrl-C 退出；输入 exit 结束）")')]),
]

for path, pairs in REPL:
    if not os.path.exists(path):
        print("!! 缺:", path)
        continue
    t = open(path, encoding="utf-8").read()
    n = 0
    for a, b in pairs:
        if a in t:
            t = t.replace(a, b)
            n += 1
    open(path, "w", encoding="utf-8", newline="\n").write(t)
    print("  %-24s 改了 %d 处" % (os.path.basename(path), n))

# 语法自检
import ast  # noqa: E402
for f in ("core.py", "main.py"):
    p = os.path.join(AG, f)
    ast.parse(open(p, encoding="utf-8").read())
    print("  %-24s 语法 OK" % f)

print("\n--- SYSTEM 提示词开头 ---")
t = open(os.path.join(AG, "core.py"), encoding="utf-8").read()
i = t.find("SYSTEM = ")
print(t[i:i + 300])
