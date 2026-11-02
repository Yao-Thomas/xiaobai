#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染底板装配图（正面），用来定位 PHONE 耳机座在哪"""
import os
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
        r"\3_开发板原理图和硬件相关文件\硬件相关文件\领航者结构图&DXF&封装库"
        r"\领航者底板\领航者ZYNQ底板结构图")
OUT = r"D:\ubuntu_iso"
for tag, fn in (("front", "领航者ZYNQ底板结构&装配图正面_V3.9.pdf"),
                ("back", "领航者ZYNQ底板结构&装配图背面_V3.9.pdf")):
    p = os.path.join(BASE, fn)
    if not os.path.exists(p):
        print("缺:", p)
        continue
    doc = fitz.open(p)
    print("%s: %d 页" % (fn, doc.page_count))
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
        o = os.path.join(OUT, "_asm_%s_%d.png" % (tag, i + 1))
        pix.save(o)
        print("   -> %s  %dx%d" % (o, pix.width, pix.height))
        # 找 PHONE / 耳机 文字位置
        for w in doc[i].get_text("words"):
            t = w[4]
            if any(k in t.upper() for k in ("PHONE", "LINE", "SPK", "MIC",
                                            "耳机", "喇叭", "音频", "AUDIO")):
                print("      文字 %-10s @ (%.0f, %.0f)" % (t, w[0], w[1]))
