#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比原版和 patch 后的 ESP32 main.cpp，只打印差异块。"""
import difflib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

A = r"C:\Projects\esp32s3_test\src\main.cpp"
B = (r"D:\总文件夹\FPGA2026_项目交接包\17_板载Agent\esp32_改造\main.cpp")

a = open(A, encoding="utf-8").read().splitlines()
b = open(B, encoding="utf-8").read().splitlines()
print("原版 %d 行 / %d 字符" % (len(a), sum(len(x) + 1 for x in a)))
print("新版 %d 行 / %d 字符" % (len(b), sum(len(x) + 1 for x in b)))
print()
n = 0
for line in difflib.unified_diff(a, b, "orig", "patched", lineterm="", n=2):
    print(line)
    n += 1
print()
print("diff 行数 =", n)
