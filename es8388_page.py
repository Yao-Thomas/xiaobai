#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ES8388 手册里寄存器描述那几页整页打出来"""
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
     r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")
doc = fitz.open(P)
want = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                         else ["8", "9"])]
for p in want:
    if 1 <= p <= doc.page_count:
        print("\n" + "#" * 88)
        print("### 第 %d 页" % p)
        print("#" * 88)
        print(doc[p - 1].get_text())
