#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_gain_regs.py —— 从 ES8388 数据手册里挖**所有跟输出增益有关的寄存器**

目的：声音已经能放了，用户想再大一点。
      软件侧 Playback(192) 和 Output1/2(33) 都已到顶。
      查还有没有没用上的增益：混合器增益、Vpp_scale 等。

★ 注意：手册正文里寄存器编号是**十进制**（"Register 39" = 0x27）。
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
       r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")

# 当前寄存器值（板子实测）
CUR = {
    0x1D: 0x00,   # DAC Control 7
    0x26: None,   # DAC Control 6
    0x27: 0xF8,   # Left Mixer
    0x28: None,   # ?
    0x29: None,   # ?
    0x2A: 0xF8,   # Right Mixer
    0x2B: 0x80,   # DAC Control 12
    0x2E: 0x21, 0x2F: 0x21, 0x30: 0x21, 0x31: 0x21,
}

doc = fitz.open(PDF)
print("=" * 88)
print("ES8388 输出增益相关寄存器")
print("=" * 88)
print("  数据手册: %s (%d 页)" % (os.path.basename(PDF), doc.page_count))
print()

# 关心的关键词
KEYS = ["vpp", "Vpp", "scale", "Mixer", "MIXER", "volume", "Volume", "Gain",
        "gain", "LD2LO", "RD2RO", "LI2LO", "RI2RO"]

alltext = []
for i in range(doc.page_count):
    t = doc[i].get_text()
    alltext.append((i, t))

# 找含 "Mixer" 或 "Vpp" 的页
print("--- 含关键增益词的页 ---")
for i, t in alltext:
    for k in ("Mixer", "Vpp", "LD2LO", "Output Volume", "DAC Control 7"):
        if k in t:
            print("  第 %d 页 含 '%s'" % (i + 1, k))
            break
print()

# 输出所有提到 LD2LO / LI2LOVOL / Vpp 的段落
print("=" * 88)
print("关键寄存器描述原文")
print("=" * 88)
for i, t in alltext:
    for kw in ("LD2LO", "LI2LOVOL", "RD2RO", "Vpp", "vpp_scale", "VPP"):
        for m in re.finditer(re.escape(kw), t):
            seg = t[max(0, m.start() - 350):m.start() + 350]
            seg = re.sub(r"\s+", " ", seg).strip()
            print("  [第%d页 %s]" % (i + 1, kw))
            print("    %s" % seg[:520])
            print()
            break
doc.close()
print("★ 要看的：混合器（0x27/0x2A）里 DAC->输出 那一路有没有增益位没拉满；")
print("        以及 0x1D 的 Vpp_scale 能不能从 3.5V 提到 4.0V。")
