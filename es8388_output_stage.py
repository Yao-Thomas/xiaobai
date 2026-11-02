#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_output_stage.py —— 从手册挖输出级寄存器（0x26~0x31）

背景：用户说"说明书上喇叭声音是可以很大的"，
      所以"声音小"是软件没调到位，不是我之前断言的硬件问题。
      我之前只验证了 0x1A/0x1B（DAC 数字音量）和 0x2E~0x31（输出音量），
      但**没有系统核对输出通路上还有哪些增益环节**。

要查的：
  * 0x26~0x2A  输出混合器（DAC -> LOUT/ROUT 的通路与增益）
  * 0x2B       （我们写的是 0x80）
  * 0x2E~0x31  输出音量（0 = -45dB, 33 = 0dB? 还是别的映射？）
  * 0x30/0x31  走喇叭的 LOUT2/ROUT2
  * DAC 到输出的完整链路里有没有别的开关/增益
"""
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
pages = [doc[i].get_text() for i in range(doc.page_count)]

# 找含 "Register 26" ... "Register 31" 的段落
print("=" * 84)
print("输出级寄存器（0x26 ~ 0x31）")
print("=" * 84)
for pno, t in enumerate(pages):
    for m in re.finditer(r"Register\s+(2[6-9A-F]|3[01])\s*[-–—]\s*([^\n]{0,60})",
                         t):
        start = m.start()
        seg = t[start:start + 1400]
        print("\n--- 第 %d 页 ---" % (pno + 1))
        print(seg.split("Register ")[0][:1200] if start > 0 else "")
        print(seg[:1200])
        print("-" * 84)

# 另外：把所有提到 LOUT2 / ROUT2 / SPK 的地方列出来
print()
print("=" * 84)
print("所有提到 LOUT2 / ROUT2 的地方")
print("=" * 84)
seen = set()
for pno, t in enumerate(pages):
    for m in re.finditer(r"(?i)(lout2|rout2|speaker|spk)", t):
        s = max(0, m.start() - 120)
        e = min(len(t), m.end() + 120)
        frag = t[s:e].replace("\n", " | ")
        key = frag[:80]
        if key in seen:
            continue
        seen.add(key)
        print("  p%-2d %s" % (pno + 1, frag))
        print()
