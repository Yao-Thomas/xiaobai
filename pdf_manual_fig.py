#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把厂家手册里"耳机插口 / 开发板背面喇叭"那两页渲染出来看实物图，
   并搜一下蜂鸣器"""
import os
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\1_领航者ZYNQ开发板出厂综合测试\【正点原子】领航者ZYNQ开发板用户快速体验_V3.2.pdf")
OUT = r"D:\ubuntu_iso"
doc = fitz.open(PDF)

for pg in (99, 100, 101):        # 0-based: 第 100/101/102 页
    p = doc[pg]
    pix = p.get_pixmap(matrix=fitz.Matrix(2.2, 2.2))
    o = os.path.join(OUT, "_man_p%d.png" % (pg + 1))
    pix.save(o)
    print("第 %d 页 -> %s  %dx%d" % (pg + 1, o, pix.width, pix.height))

print("\n=== 搜 蜂鸣 / BEEP / 喇叭 / 外接 ===")
for i in range(doc.page_count):
    t = doc[i].get_text()
    for kw in ("蜂鸣", "BEEP", "beep", "外接", "喇叭", "扬声器"):
        for m in re.finditer(kw, t):
            a = max(0, m.start() - 60)
            b = min(len(t), m.end() + 90)
            seg = t[a:b].replace("\n", " ")
            print("  p%-4d [%s] ...%s..." % (i + 1, kw, seg))
