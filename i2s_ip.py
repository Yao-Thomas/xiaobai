#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读 I2S 发送器 IP 的 GUI 参数说明（找数据格式相关的线索）"""
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

p = (r"D:\Xilinx\2026.1\data\ip\xilinx\i2s_transmitter_v1_0\xgui"
     r"\i2s_transmitter_v1_0.tcl")
t = open(p, encoding="utf-8", errors="replace").read()

for m in re.finditer(r"tooltip\s*\{([^}]*)\}", t):
    print("  tooltip:", m.group(1).strip())

print("--- 参数名 ---")
print(sorted(set(re.findall(r'add_param\s+\S+\s+-name\s+"([^"]+)"', t))))

print("--- 含 data/width/format 的行 ---")
for ln in t.splitlines():
    if re.search(r"(?i)data|width|format|aes|pcm|slot", ln):
        print("   ", ln.strip()[:160])
