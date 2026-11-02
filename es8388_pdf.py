#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 ES8388 数据手册里挖寄存器说明（重点：上电/使能/接口）"""
import os
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
     r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")
doc = fitz.open(P)
print("页数:", doc.page_count)
text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
print("总字符:", len(text))

KEYS = ["CONTROL1", "CONTROL2", "CHIPPOWER", "ADCPOWER", "DACPOWER",
        "MASTERMODE", "ADCCONTROL", "DACCONTROL", "SLAVE", "MASTER",
        "MCLK", "BCLK", "LRCK", "SCLK", "Power", "power", "Enable", "enable"]

# 找含 "Reg" 和寄存器的页
pages = [doc[i].get_text() for i in range(doc.page_count)]
print("\n=== 每页关键词密度 ===")
for i, t in enumerate(pages):
    sc = sum(t.count(k) for k in KEYS)
    if sc > 5:
        print("  第 %2d 页  相关度 %d" % (i + 1, sc))

# 打印寄存器映射那几页
for i, t in enumerate(pages):
    if ("CONTROL1" in t or "CHIPPOWER" in t or "MASTERMODE" in t) and \
            ("Register" in t or "Reg" in t or "0x00" in t or "Default" in t):
        print("\n" + "=" * 84)
        print("### 第 %d 页" % (i + 1))
        print(t[:5200])
