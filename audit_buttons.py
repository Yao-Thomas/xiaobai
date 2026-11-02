#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_buttons.py —— 排查"只加了点击区域、忘了画出来"的按钮。

这个 bug 我在这个设置 App 里犯了两次（提示音页的"设为默认/停止"、
音量页的微调按钮和"试听/停止"）—— 表现是"能点但看不见"。
这里做一个静态检查：凡是 rows.append(([...], action)) 的地方，
往前几行必须能找到对应的绘制调用（btn / scr.rrect / draw_list）。
"""
import io
import os
import re
import sys

TARGETS = sys.argv[1:] or ["ui/apps_settings.py"]
fail = 0

for path in TARGETS:
    src = io.open(path, encoding="utf-8").read()
    lines = src.splitlines()
    print("\n=== %s ===" % path)
    for i, ln in enumerate(lines):
        if "rows.append((" not in ln:
            continue
        # 往前 6 行找绘制调用
        ctx = "\n".join(lines[max(0, i - 6):i + 1])
        if ("btn(scr" in ctx or "draw_list(" in ctx or
                "btn(scr," in ctx or "scr.rrect" in ctx):
            continue
        print("  [!] 第 %d 行只加了点击区域, 附近没看到绘制:" % (i + 1))
        print("      " + ln.strip())
        fail += 1

print("\n%s" % ("OK: 没发现问题" if not fail else "共 %d 处可疑" % fail))
sys.exit(1 if fail else 0)
