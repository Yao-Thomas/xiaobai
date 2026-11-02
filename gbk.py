#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 GBK 乱码的源码行解码回中文"""
import sys
import re

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

path = sys.argv[1]
pats = sys.argv[2:]
lines = open(path, "rb").read().decode("utf-8", "replace").split("\n")
# 该文件每个真实行之间夹了空行, 先过滤
lines = [l for l in lines if l.strip() != ""]

out = []
for i, l in enumerate(lines):
    if pats and not any(p in l for p in pats):
        continue
    try:
        fixed = l.encode("utf-8", "surrogateescape").decode("gbk", "replace")
    except Exception:
        fixed = l
    out.append("%4d| %s" % (i + 1, fixed))
print("\n".join(out))
