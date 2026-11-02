#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查找 HLS 二进制里的时间格式串 (用于绕过 core_revision 溢出)"""
import os, sys

ROOTS = [
    r"D:\Xilinx\Vivado\2018.3\lib\win64.o",
    r"D:\Xilinx\Vivado\2018.3\bin",
    r"D:\Xilinx\Vivado\2018.3\lib",
]
PATTERNS = [b"%y%m%d%H%M", b"%y%m%d", b"%Y%m%d%H%M", b"%y%m%d%H%M%S"]

hits = []
for root in ROOTS:
    if not os.path.isdir(root):
        continue
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 300 * 1024 * 1024:
                    continue
                with open(p, "rb") as f:
                    data = f.read()
            except Exception:
                continue
            for pat in PATTERNS:
                i = data.find(pat)
                if i >= 0:
                    # 看上下文
                    ctx = data[max(0, i - 40):i + 40]
                    hits.append((p, pat.decode(), i, ctx))

print("找到 %d 处:" % len(hits))
for p, pat, i, ctx in hits[:20]:
    print("")
    print("  文件: %s" % p)
    print("  模式: %s  偏移: 0x%X" % (pat, i))
    # 可打印上下文
    s = "".join(chr(c) if 32 <= c < 127 else "." for c in ctx)
    print("  上下文: %s" % s)
