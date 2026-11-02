#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从厂家的《快速体验》手册里找音频/耳机/喇叭/蜂鸣器相关说明"""
import os
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\1_领航者ZYNQ开发板出厂综合测试\【正点原子】领航者ZYNQ开发板用户快速体验_V3.2.pdf")
print("PDF:", os.path.basename(PDF), os.path.getsize(PDF))
doc = fitz.open(PDF)
print("页数:", doc.page_count)

KEYS = ["音频", "耳机", "喇叭", "扬声器", "蜂鸣", "音乐", "播放", "放音",
        "AUDIO", "PHONE", "SPK", "BEEP", "LINE_IN", "插入", "短接", "跳线"]

hits = []
for i in range(doc.page_count):
    t = doc[i].get_text()
    score = sum(t.count(k) for k in KEYS)
    if score:
        hits.append((i + 1, score, t))

hits.sort(key=lambda x: -x[1])
print("\n命中页（按相关度）:", [(h[0], h[1]) for h in hits[:15]])

for pg, sc, t in hits[:6]:
    print("\n" + "=" * 80)
    print("### 第 %d 页 (相关度 %d)" % (pg, sc))
    # 只打含关键词的片段
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    for j, l in enumerate(lines):
        if any(k in l for k in KEYS):
            a = max(0, j - 2)
            b = min(len(lines), j + 3)
            for k in range(a, b):
                mark = ">>" if k == j else "  "
                print("%s %s" % (mark, lines[k][:130]))
            print("   ---")
