#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md8002a_gain.py —— 从 V3.9 原理图里抠出 MD8002A 功放的增益电阻

目的：软件增益已全部到顶，想再响只能改硬件。
      MD8002A 的增益由反馈电阻决定，要把 R40 从 20K 换成 47K。
      这里把元件位号、阻值、封装都确认清楚，方便直接动手。
"""
import os
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料"
       r"\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\3_开发板原理图和硬件相关文件\领航者ZYNQ底板原理图_V3.9.pdf")

doc = fitz.open(PDF)
print("=" * 88)
print("MD8002A 功放周边元件（找增益电阻 R39/R40）")
print("=" * 88)

# 找含 MD8002 的页
pages = [i for i in range(doc.page_count) if "8002" in doc[i].get_text()]
print("  含 MD8002 的页: %s" % [p + 1 for p in pages])
print()

for pi in pages:
    page = doc[pi]
    words = page.get_text("words")
    print("=" * 88)
    print("第 %d 页：MD8002A 附近的文字" % (pi + 1))
    print("=" * 88)
    # 找 MD8002 的位置
    anchors = [w for w in words if "8002" in w[4]]
    for a in anchors:
        ax, ay = a[0], a[1]
        print("  锚点 '%s' 在 (%.0f, %.0f)" % (a[4], ax, ay))
        # 半径 260 内的所有文字
        near = [w for w in words
                if abs(w[0] - ax) < 300 and abs(w[1] - ay) < 200]
        near.sort(key=lambda w: (round(w[1] / 4), w[0]))
        line = []
        lasty = None
        for w in near:
            if lasty is None or abs(w[1] - lasty) < 5:
                line.append(w[4])
            else:
                print("    " + " ".join(line))
                line = [w[4]]
            lasty = w[1]
        if line:
            print("    " + " ".join(line))
        print()

doc.close()
print("★ 要看的：")
print("  * R39（输入电阻）和 R40（反馈电阻）的阻值")
print("  * 封装（0603 / 0805）—— 决定买什么料")
print("  * 把 R40 换成 47K，增益从 ~2 倍提到 ~4.7 倍（约 +7 dB）")
