#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_jack.py —— 查原理图上耳机/喇叭座子怎么接的

目的：回答"插外置扬声器能不能立刻改善音质"。
关键看：
  * 有没有 3.5mm 耳机座（PHONE）或喇叭座（SPK）
  * 座子是接在 MD8002A 功放【之前】(line out，绕过功放) 还是【之后】
  * 插拔检测脚怎么接的
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
       r"\3_开发板原理图和硬件相关文件\领航者ZYNQ底板原理图_V3.9.pdf")

doc = fitz.open(PDF)
print("=" * 84)
print("耳机 / 喇叭座 的连接方式")
print("=" * 84)
print()

KEYS = ["PHONE", "SPK", "HP_", "HEAD", "EAR", "LOUT", "ROUT", "8002",
        "JACK", "LINE_OUT", "LINEOUT"]

for i in range(doc.page_count):
    page = doc[i]
    words = page.get_text("words")
    hits = [w for w in words if any(k in w[4].upper() for k in KEYS)]
    if not hits:
        continue
    print("--- 第 %d 页 ---" % (i + 1))
    for h in hits:
        ax, ay = h[0], h[1]
        near = [w for w in words if abs(w[0] - ax) < 260 and abs(w[1] - ay) < 60]
        near.sort(key=lambda w: (round(w[1] / 5), w[0]))
        line, lasty = [], None
        parts = []
        for w in near:
            if lasty is None or abs(w[1] - lasty) < 6:
                line.append(w[4])
            else:
                parts.append(" ".join(line))
                line = [w[4]]
            lasty = w[1]
        if line:
            parts.append(" ".join(line))
        ctx = " | ".join(parts)[:300]
        print("  [%s] 附近: %s" % (h[4], ctx))
    print()

doc.close()
print("=" * 84)
print("★ 判读要点：")
print("  * 若 3.5mm 座接在 MD8002A 的【输入端】(line out) -> 插外置有源音箱")
print("    就完全绕过那个小喇叭和功放，音质会大幅改善")
print("  * 若座子接在功放【输出端】-> 是耳机口，但可能被功放增益放大过头")
print("  * SPK 座子接功放输出 -> 只换喇叭也能改善（至少有了外置腔体）")
