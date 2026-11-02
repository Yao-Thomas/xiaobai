#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_start_bug2.py —— 修桌面「开始」按钮的两个 bug（精确判据版）

Bug 1：「开始」点了没反应
    _do_tap() 在 menu_open 分支里先无条件 self.menu_open = False，
    再判是否点到「开始」，点到又设回 True —— 先关再开，看起来没反应。

Bug 2：首页/图标页左下角看不见的「开始」区域却能点
    旧任务栏的点击区域 [12, 554, 116, 590] 无条件生效，
    但那个位置画的是 home 的「全部应用」按钮（x=26..196）。
    两条路径重叠 -> 多出来的那条成了"幽灵区域"。

修法：两处判定都加 `H is None and` ——
     有 home 外壳时，「全部应用」已能开菜单（走 home.hit() -> ("menu",None)）。

★ 上次用 `"幽灵" in src` 当判据太松，匹配到了别处已有的注释，误判成"已修"。
  这次用精确标记 `MARK`。
"""
import ast
import io
import shutil
import sys
import time

P = "/home/zynq/ui/desktop.py"
MARK = "STARTBTN_FIX_V2"          # 精确判据

src = io.open(P, encoding="utf-8").read()

if MARK in src:
    print("  真的已经修过了（找到 %s），跳过" % MARK)
    sys.exit(0)

shutil.copy2(P, P + ".bak_startfix_" + time.strftime("%Y%m%d_%H%M%S"))
print("  已备份")

HIT = "if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):"

count = src.count(HIT)
print("  找到 %d 处旧「开始」判定" % count)
if count != 2:
    print("  ⚠ 预期 2 处，实际 %d 处，先停下来看看" % count)
    sys.exit(1)

# 两处的缩进不同，按出现顺序分别替换
# 第 1 处：menu_open 分支里，缩进 16 空格
old1 = ("                self.menu_open = False\n"
        "                if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):\n"
        "                    self.menu_open = True\n")
new1 = ("                self.menu_open = False\n"
        "                # " + MARK + "：旧任务栏「开始」只在没有 home 外壳时启用。\n"
        "                # 有 home 时左下角画的是「全部应用」(home.MENU_BTN, x=26..196)，\n"
        "                # 这里再拦一次会变成【先关再开】，看起来像点了没反应。\n"
        "                if H is None and hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):\n"
        "                    self.menu_open = True\n")

# 第 2 处：旧任务栏段，缩进 8 空格
old2 = ("        # ---------- 旧任务栏的\"开始\"按钮 (只在菜单锚定时才画出来) ----------\n"
        "        if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):\n"
        "            self.menu_open = True\n")
new2 = ("        # ---------- 旧任务栏的\"开始\"按钮 ----------\n"
        "        # " + MARK + "：只有【没有 home 外壳】时才启用这条。\n"
        "        # 有 home 时那个位置画的是「全部应用」，这块区域是看不见的\n"
        "        # \"幽灵按钮\"（点了会突然展开菜单）。\n"
        "        if H is None and hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):\n"
        "            self.menu_open = True\n")

ok = 0
if old1 in src:
    src = src.replace(old1, new1, 1)
    ok += 1
    print("  ✓ 修 1（menu_open 分支）")
else:
    print("  ✗ 修 1 没匹配")

if old2 in src:
    src = src.replace(old2, new2, 1)
    ok += 1
    print("  ✓ 修 2（旧任务栏段）")
else:
    print("  ✗ 修 2 没匹配")

if ok != 2:
    print("  只成功 %d/2，不写回，避免半成品" % ok)
    sys.exit(1)

io.open(P, "w", encoding="utf-8").write(src)
ast.parse(io.open(P, encoding="utf-8").read())
print("  语法 OK，已写回")

print()
print("  改后的两处：")
for i, line in enumerate(io.open(P, encoding="utf-8"), 1):
    if "H is None and hit" in line or MARK in line:
        print("    %d: %s" % (i, line.rstrip()))
print()
print("  剩余未加保护的旧判定: %d 处（应为 0）"
      % io.open(P, encoding="utf-8").read().count(
          "        if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):"))
