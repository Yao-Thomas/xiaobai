#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_start_bug3.py —— 用正则匹配缩进，不再死抠空格

修两处旧任务栏「开始」判定：给它们加 `H is None and` 保护。
"""
import ast
import io
import re
import shutil
import sys
import time

P = "/home/zynq/ui/desktop.py"
MARK = "STARTBTN_FIX_V3"

src = io.open(P, encoding="utf-8").read()
if MARK in src:
    print("  已修过，跳过")
    sys.exit(0)

shutil.copy2(P, P + ".bak_startfix3_" + time.strftime("%Y%m%d_%H%M%S"))
print("  已备份")

# 匹配：<缩进>if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
# 且这一行前面没有 "H is None and"
pat = re.compile(
    r"^(?P<ind>[ \t]*)if hit\(\[12, 600 - TB_H \+ 10, 116, 600 - 10\], x, y\):",
    re.M)

matches = list(pat.finditer(src))
print("  找到 %d 处旧判定" % len(matches))
if len(matches) != 2:
    print("  ⚠ 预期 2 处，实际 %d，停下" % len(matches))
    sys.exit(1)

# 从后往前替换，避免偏移错乱
out = src
n = 0
for m in reversed(matches):
    ind = m.group("ind")
    old_line = m.group(0)
    new_line = ("%s# %s: 旧任务栏「开始」只在没有 home 外壳时启用。\n"
                "%s# 有 home 时左下角画的是「全部应用」(home.MENU_BTN)，\n"
                "%s# 两条点击路径重叠会变成【看不见却能点】的幽灵区域；\n"
                "%s# menu_open 分支里还会变成【先关再开】，看着像没反应。\n"
                "%sif H is None and hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):"
                % (ind, MARK, ind, ind, ind, ind))
    out = out[:m.start()] + new_line + out[m.end():]
    n += 1

io.open(P, "w", encoding="utf-8").write(out)
ast.parse(io.open(P, encoding="utf-8").read())
print("  ✓ 改了 %d 处，语法 OK" % n)
print()

print("  改后的位置：")
for i, line in enumerate(io.open(P, encoding="utf-8"), 1):
    if "H is None and hit" in line or MARK in line:
        print("    %d: %s" % (i, line.rstrip()))

# 复查：还有没有没保护的
left = len(re.findall(
    r"^[ \t]*if hit\(\[12, 600 - TB_H \+ 10, 116, 600 - 10\], x, y\):",
    io.open(P, encoding="utf-8").read(), re.M))
print()
print("  剩余未保护的旧判定: %d 处（应为 0）" % left)
sys.exit(0 if left == 0 else 1)
