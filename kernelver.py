#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernelver.py —— 从 zImage/FIT kernel 里抠出 "Linux version ..." 字符串"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

for p in sys.argv[1:]:
    try:
        b = open(p, "rb").read()
    except OSError as e:
        print("%s: %s" % (p, e))
        continue
    print("=" * 74)
    print(" %s  (%d 字节)" % (p, len(b)))
    print("=" * 74)
    seen = set()
    for m in re.finditer(rb"Linux version [\x20-\x7e]{10,140}", b):
        s = m.group().decode()
        if s not in seen:
            seen.add(s)
            print("   %s" % s)
    for m in re.finditer(rb"gcc version [\x20-\x7e]{5,80}", b):
        s = m.group().decode()
        if s not in seen:
            seen.add(s)
            print("   %s" % s)
    # 有没有 aic8800 / wlan 相关
    for k in (b"aic8800", b"AIC8800", b"aicwf", b"wlan"):
        if k in b:
            print("   含 %-10s ✓" % k.decode())
    if not seen:
        print("   (没找到版本字符串 —— 可能是压缩过的内核)")
    print()
