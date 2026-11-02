#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_amp_v36_v39.py —— 对比 V3.6(WM8960) 和 V3.9(ES8388) 的音频/功放电路

为什么要比：
  用户说"说明书上喇叭声音是可以很大的"，所以"声音小"可能是软件没调到位。
  但我已经把 codec 侧所有增益寄存器都核对到顶满了。
  那剩下的就是**功放增益**（R39/R40 决定的）。
  如果厂家在 V3.7 -> V3.9 换 codec 时**改过功放电阻**，
  说明他们知道要补偿什么；没改的话就是沿用原设计。

用 PyMuPDF 从原理图 PDF 里抽文字 + 坐标，找音频相关的元件。
"""
import os
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = (r"D:\总文件夹\FPGA2026\板卡资料"
        r"\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)")
PDFS = [
    ("V3.9 (ES8388)",
     os.path.join(ROOT, r"3_开发板原理图和硬件相关文件"
                        r"\领航者ZYNQ底板原理图_V3.9.pdf")),
    ("V3.6 (WM8960)",
     os.path.join(ROOT, r"9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）"
                        r"\3_开发板原理图\领航者ZYNQ底板原理图_V3.6.pdf")),
]

# 关心这些关键词（音频 + 功放）
KEYS = ["ES8388", "WM8960", "MD8002", "8002", "SPK", "SPK+", "SPK-",
        "LOUT", "ROUT", "MIC", "PHONE", "LINE_IN", "LINEIN",
        "R39", "R40", "R41", "R36", "R37", "R38", "C39", "C95",
        "C102", "C104", "C108", "U24"]

for label, path in PDFS:
    print("=" * 88)
    print("### %s" % label)
    print("    文件:", os.path.basename(path), "存在:", os.path.exists(path))
    print("=" * 88)
    if not os.path.exists(path):
        print("  [!] 文件不在\n")
        continue
    doc = fitz.open(path)
    print("  页数:", doc.page_count)
    # 找含音频关键词最多的页
    best = []
    for i in range(doc.page_count):
        t = doc[i].get_text()
        sc = sum(t.upper().count(k.upper()) for k in KEYS)
        if sc > 3:
            best.append((sc, i, t))
    best.sort(reverse=True)
    print("  相关页(按关键词密度):", [(s, i + 1) for s, i, _ in best[:5]])
    if not best:
        print("  (没抽到文字 —— 可能是矢量图，需要转图片看)\n")
        continue
    sc, pno, t = best[0]
    print()
    print("  --- 第 %d 页抽到的音频相关片段 ---" % (pno + 1))
    # 只打印含关键元件名的行
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    shown = 0
    for i, ln in enumerate(lines):
        if re.search(r"(?i)(es8388|wm8960|md8002|8002|spk|r39|r40|r41|"
                     r"lout|rout|u24|c39|c95|c102|c104|c108|20k|680|2k)",
                     ln):
            ctx = " | ".join(lines[max(0, i - 1):i + 2])
            print("   ", ctx[:170])
            shown += 1
            if shown >= 30:
                break
    print()
