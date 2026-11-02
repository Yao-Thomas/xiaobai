#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_start_bug.py —— 修桌面「开始」按钮的两个 bug

Bug 1：「开始」点了没反应
    _do_tap() 在 menu_open 分支里先无条件 self.menu_open = False，
    再判是否点到「开始」，点到又设回 True —— 先关再开，看起来没反应。

Bug 2：首页看不见的「开始」区域却能点
    旧任务栏的点击区域 [12, 554, 116, 590] 在 _do_tap() 里无条件生效，
    但首页/图标页左下角画的是 home 的「全部应用」按钮（x=26..196）。
    两条路径重叠 -> 多出来的那条成了"幽灵区域"。

修法：旧任务栏那两处判定都加条件 —— 只有【没有 home 外壳】时才启用。
     （有 home 时，「全部应用」已经能开菜单，走的是 home.hit() -> ("menu",None)）
"""
import io
import shutil
import sys
import time

P = "/home/zynq/ui/desktop.py"

src = io.open(P, encoding="utf-8").read()

if "幽灵" in src:
    print("  已经修过了，跳过")
    sys.exit(0)

shutil.copy2(P, P + ".bak_startbug_" + time.strftime("%Y%m%d_%H%M%S"))
print("  已备份")

OLD_TB = "600 - TB_H + 10, 116, 600 - 10"

# ── 修 1：menu_open 分支里那条（约 1503 行）──
old1 = """            self.menu_open = False
            if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
                self.menu_open = True
                self.draw()
                return
"""
new1 = """            self.menu_open = False
            # 旧任务栏的"开始"按钮：只有【没有新首页外壳】时才启用。
            # 有 home 时左下角画的是「全部应用」(home.MENU_BTN)，走 home.hit()
            # 那条路开菜单；这里再拦一次会变成"先关再开"，看着像没反应。
            if H is None and hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
                self.menu_open = True
                self.draw()
                return
"""
if old1 in src:
    src = src.replace(old1, new1, 1)
    print("  ✓ 修 1：menu_open 分支的「开始」判定已加 H is None 条件")
else:
    print("  ✗ 修 1 没找到匹配（代码可能已改），需要手工看")

# ── 修 2：旧任务栏那条（约 1561 行）──
old2 = """        # ---------- 旧任务栏的"开始"按钮 (只在菜单锚定时才画出来) ----------
        if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
            self.menu_open = True
            self.draw()
            return
"""
new2 = """        # ---------- 旧任务栏的"开始"按钮 ----------
        # ★ 只有【没有 home 外壳】时才启用这条：有 home 时左下角画的是
        #   「全部应用」，这块区域是看不见的"幽灵按钮"（点了会突然展开菜单）。
        if H is None and hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
            self.menu_open = True
            self.draw()
            return
"""
if old2 in src:
    src = src.replace(old2, new2, 1)
    print("  ✓ 修 2：旧任务栏的「开始」幽灵区域已加 H is None 条件")
else:
    print("  ✗ 修 2 没找到匹配，需要手工看")

io.open(P, "w", encoding="utf-8").write(src)

# 校验
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("  语法 OK")

# 展示改后的两处
for i, line in enumerate(io.open(P, encoding="utf-8"), 1):
    if "H is None and hit" in line or "幽灵" in line:
        print("  %d: %s" % (i, line.rstrip()))
