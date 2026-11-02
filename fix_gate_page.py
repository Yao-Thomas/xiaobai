#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_gate_page.py —— 修掉刚才把 GATE_PAGE 改坏的问题

坏的原因：在 Python 三引号字符串里写了 Windows 路径 D:\\ubuntu_iso\\...，
其中的 \\u 被当成 Unicode 转义 -> SyntaxError: truncated \\uXXXX escape。
修法：显示文本里用正斜杠（HTML 里显示效果一样，且不需要转义）。
"""
import io
import re

P = "dsh_proxy.py"
src = io.open(P, encoding="utf-8").read()

bad = "D:\\ubuntu_iso\\start_proxy.bat"
if bad in src:
    src = src.replace(bad, "D:/ubuntu_iso/start_proxy.bat")
    print("已把反斜杠路径换成正斜杠")

# 顺手把所有潜在的三引号字符串里的裸 \\u 转义修掉（只针对 GATE_PAGE 段落）
m = re.search(r'GATE_PAGE = """.*?"""', src, re.S)
if m:
    seg = m.group(0)
    if "\\u" in seg and "\\\\u" not in seg:
        print("警告: GATE_PAGE 里仍有 \\u 转义")

io.open(P, "w", encoding="utf-8").write(src)

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("syntax OK")
