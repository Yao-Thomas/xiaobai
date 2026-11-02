#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把"没有 back_hit"的那几个 App 的点击处理段打出来，看它们怎么退出"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
TARGET = ["apps_about.py", "apps_browser.py", "apps_fight.py",
          "apps_gpuperf.py", "apps_mines.py", "apps_net.py",
          "apps_sys.py", "apps_wifi.py"]

for fn in TARGET:
    src = open(os.path.join(D, fn), encoding="utf-8").read()
    lines = src.splitlines()
    print("=" * 84)
    print("### %s  (%d 行)" % (fn, len(lines)))
    # 找顶层 run() 与其中的 tap/up 分支
    idx = [i for i, l in enumerate(lines) if re.match(r"^def run\(", l)]
    for a in idx:
        seg = lines[a:a + 400]
        for j, l in enumerate(seg, a + 1):
            s = l.strip()
            if re.search(r"(k == \"(up|down|tap)\"|tap\(x, y\)|hit\(|返回|退出|"
                         r"back|menu|def tap)", s):
                print("  %4d| %s" % (j, l[:130]))
