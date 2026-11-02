#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找 ES8388 的引脚定义页 + ADC 控制寄存器页"""
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
     r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")
doc = fitz.open(P)
for i in range(doc.page_count):
    t = doc[i].get_text()
    tag = []
    if "DACLRC" in t or "ADCLRC" in t:
        tag.append("LRC引脚")
    if "Register 8 " in t or "Register 12" in t or "Register 13" in t \
            or "Register 8 –" in t:
        tag.append("ADC/主从寄存器")
    if "PIN DESCRIPTION" in t.upper() or "Pin Description" in t:
        tag.append("引脚表")
    if tag:
        print("第 %2d 页: %s" % (i + 1, " / ".join(tag)))
