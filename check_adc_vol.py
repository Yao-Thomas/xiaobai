#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看厂家驱动里两条音量控制的 invert 参数，以及 0x10/0x11 的注释"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\总文件夹\FPGA2026_项目交接包\14_音频勘验\es8388_vendor.c")
raw = open(P, "rb").read()
# 文件是 utf-8 保存但中文是 gbk 字节流被当 utf-8 存过, 逐行试着还原
lines = raw.decode("utf-8", "replace").splitlines()

print("=== SOC_DOUBLE_R_TLV 控制定义（关键看最后那个 invert 参数）===")
pat = re.compile(r'SOC_DOUBLE_R_TLV\(\s*"([^"]+)"')
for i, l in enumerate(lines):
    if "SOC_DOUBLE_R_TLV" in l:
        # 把后面 3 行接起来看参数
        seg = " ".join(x.strip() for x in lines[i:i + 3])
        m = pat.search(seg)
        name = m.group(1) if m else "?"
        nums = re.findall(r",\s*(\d+)\s*,", seg)
        print("  %-28s | %s" % (name, seg[:150]))

print()
print("=== 0x10 / 0x11 那两行的原始注释 ===")
for i, l in enumerate(lines):
    if re.search(r"regmap_write\(\s*\w+,\s*0x1[01]\s*,", l):
        try:
            fixed = l.encode("utf-8", "surrogateescape").decode("gbk", "replace")
        except Exception:
            fixed = l
        print("  line %-5d %s" % (i + 1, fixed.strip()[:130]))

print()
print("=== adc_tlv / dac_tlv 定义 ===")
for l in lines:
    if "adc_tlv" in l or "dac_tlv" in l:
        print("  ", l.strip()[:120])
