#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 audio_formatter HDL 里 MM2S 输出格式选择那一段完整打出来（带行号）"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\Xilinx\2026.1\data\ip\xilinx\audio_formatter_v1_0\hdl"
     r"\audio_formatter_v1_0_rfs.v")
t = open(P, encoding="utf-8", errors="replace").read()
lines = t.splitlines()

# 找 AES_TO_PCM 所在的 generate 起点
start = None
for i, ln in enumerate(lines):
    if "AES_TO_PCM" in ln and "else if" in ln:
        start = i
        break
print("AES_TO_PCM 分支在第 %d 行" % (start + 1))
# 往前找 generate
for j in range(start, max(0, start - 80), -1):
    if "generate" in lines[j]:
        start = j
        break

end = start
for j in range(start, min(len(lines), start + 220)):
    if "aes_enc1" in lines[j]:
        end = j + 40
print("打印第 %d ~ %d 行" % (start + 1, end))
print("=" * 100)
for j in range(start, min(len(lines), end)):
    print("%5d| %s" % (j + 1, lines[j]))
