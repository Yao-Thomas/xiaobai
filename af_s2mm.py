#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看 audio formatter 的 S2MM（录音）侧：AES 解码器能不能像 MM2S 那样旁路掉"""
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\Xilinx\2026.1\data\ip\xilinx\audio_formatter_v1_0\hdl"
     r"\audio_formatter_v1_0_rfs.v")
L = open(P, encoding="utf-8", errors="replace").read().splitlines()

print("=== 所有 C_S2MM_DATAFORMAT 出现处 ===")
for i, ln in enumerate(L):
    if "C_S2MM_DATAFORMAT" in ln:
        print("%5d| %s" % (i + 1, ln.strip()[:140]))

print()
print("=== aes_dec 实例化 ===")
for i, ln in enumerate(L):
    if "aes_dec" in ln:
        print("%5d| %s" % (i + 1, ln.strip()[:140]))

print()
print("=== 找出 S2MM 的 AES_TO_PCM 那个 generate 块，整段打出来 ===")
start = None
for i, ln in enumerate(L):
    if "C_S2MM_DATAFORMAT" in ln and "generate" in ln:
        start = i
        break
if start is None:
    for i, ln in enumerate(L):
        if "S2MM_DATAFORMAT == 1" in ln:
            start = i
            break
print("起点第 %d 行" % (start + 1 if start is not None else 0))
if start is not None:
    for i in range(max(0, start - 4), min(len(L), start + 70)):
        print("%5d| %s" % (i + 1, L[i][:150]))
