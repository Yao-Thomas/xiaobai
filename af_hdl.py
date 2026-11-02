#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 audio_formatter HDL 里找 MM2S 把 DDR 32bit 字喂给 aes_enc/pcm 的那一段，
   看它取的是高 24 位还是低 24 位。"""
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\Xilinx\2026.1\data\ip\xilinx\audio_formatter_v1_0\hdl"
     r"\audio_formatter_v1_0_rfs.v")
t = open(P, encoding="utf-8", errors="replace").read()

# 1) aes_enc 的实例化点（不是 module 定义）
insts = [m.start() for m in re.finditer(r"audio_formatter_v1_0_18_aes_enc\s+", t)]
print("aes_enc 出现位置:", insts)
for i in insts:
    seg = t[i:i + 1400]
    if "module audio_formatter_v1_0_18_aes_enc" in t[max(0, i - 60):i + 60]:
        print("(跳过 module 定义)")
        continue
    print("=" * 90)
    print(seg)

# 2) 找 in_data 的连接
print("=" * 90)
print("--- 搜 .in_data 连接 ---")
for m in re.finditer(r"\.in_data\s*\(([^)]*)\)", t):
    a = max(0, m.start() - 400)
    print("..." + t[a:m.end() + 200].replace("\n", "\n"))
    print("-" * 60)
