#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确认 pcm_data_width 是从 AUD_CTRL 寄存器（可运行时改）来的，
   而不是综合期常量 —— 这决定我们能不能"关掉 AES 编码"。"""
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\Xilinx\2026.1\data\ip\xilinx\audio_formatter_v1_0\hdl"
     r"\audio_formatter_v1_0_rfs.v")
lines = open(P, encoding="utf-8", errors="replace").read().splitlines()

print("=== 所有 pcm_data_width 出现处 ===")
for i, ln in enumerate(lines):
    if "pcm_data_width" in ln and ("assign" in ln or "wire" in ln or "reg" in ln
                                   or "<=" in ln or "=" in ln):
        if "pcm_data_width ==" in ln and "?" in ln:
            continue          # 这些是用法，不是定义
        print("%5d| %s" % (i + 1, ln.strip()[:150]))

print()
print("=== 找 audio_ctrl / data_width 字段解码 ===")
for i, ln in enumerate(lines):
    s = ln.strip()
    if re.search(r"(?i)(data_?width|aud_ctrl|ctrl_reg)", s) and (
            "<=" in s or "assign" in s or "wire" in s or "[" in s):
        if len(s) > 160:
            continue
        print("%5d| %s" % (i + 1, s[:150]))
