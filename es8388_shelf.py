#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_shelf.py —— 确认 ES8388 是否自带 shelving 滤波器（放音侧 EQ）

如果自带，就完全不用写 RTL —— 直接 i2cset 配系数即可。
"""
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料"
       r"\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")

doc = fitz.open(PDF)
print("=" * 80)
print("ES8388 的 shelving 滤波器（放音侧 EQ）")
print("=" * 80)
print()

for i in range(doc.page_count):
    t = doc[i].get_text()
    if "Shelving" in t or "shelving" in t:
        print("--- 第 %d 页 ---" % (i + 1))
        # 抓 shelving 附近的段落
        for m in re.finditer(r"[Ss]helving", t):
            seg = t[max(0, m.start() - 500):m.start() + 700]
            seg = re.sub(r"\s+", " ", seg).strip()
            print("  " + seg[:900])
            print()
            break
doc.close()
print("=" * 80)
print("★ 要点：")
print("  * Shelving_a / Shelving_b 各 30 bit 系数，分 4 个寄存器写（Reg.30~37）")
print("  * 如果这些滤波器作用在【DAC 放音】路径上，就能用 i2cset 直接做 EQ，")
print("    完全不用改 FPGA/RTL，也不用重建 bitstream")
print("  * 若是 ADC 侧，就只能用于录音")
