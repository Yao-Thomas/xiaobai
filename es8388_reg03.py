#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_reg03.py —— 从官方手册里挖出寄存器 0x03 (ADCPOWER) 的确切位定义

为什么：
  交接文档第 287 行说"0x03 bit3 = PdnMICB，所以厂家值 0x59 把麦克风偏置关了"，
  但同一份文档第 82 行（看原理图得出的）说"偏置来自外部 +5V 经 R36"。
  两者矛盾。而 audio_svc.py 的默认值 0x03=0x51 正是按前者改的。

  所以要从**手册**确认 bit3 到底是什么，才能判断谁对。
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

print("=" * 78)
print("1) 所有提到 ADCPOWER / MICB / Bias 的地方")
print("=" * 78)
for i, t in enumerate(pages):
    for m in re.finditer(r"(?i)(adcpower|pdnmicb|micbias|mic bias|biasgen|"
                         r"pdnadc|adcbias)", t):
        s = max(0, m.start() - 90)
        e = min(len(t), m.end() + 90)
        frag = t[s:e].replace("\n", " | ")
        print("  p%-2d %s" % (i + 1, frag))
        print()

print("=" * 78)
print("2) 含寄存器地址表的那几页（找 'Reg' 和 '0x03'）")
print("=" * 78)
for i, t in enumerate(pages):
    if re.search(r"0x0?3\b", t) and re.search(r"(?i)(Default|R/W|Register)", t):
        print("\n--- 第 %d 页 ---" % (i + 1))
        print(t[:3500])
