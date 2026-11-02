#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_dump_regs.py —— 把手册里寄存器 0x00~0x0B 的位定义完整打印出来

重点要看：
  Reg 0x03 (ADCPOWER)  —— 每一位是哪个模块的电源
  Reg 0x0A             —— 输入选择（LIN1/RIN1 差分还是单端？）
  Reg 0x09/0x0B        —— ADC 相关
"""
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
     r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")

doc = fitz.open(P)

# 位定义在 13~17 页附近
for pno in (13, 14, 15, 16, 17):
    if pno - 1 >= doc.page_count:
        continue
    t = doc[pno - 1].get_text()
    if not t.strip():
        continue
    print("=" * 80)
    print("### 第 %d 页" % pno)
    print("=" * 80)
    print(t)
    print()
