#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui_struct.py —— 摸清 desktop.py 的编码/常量/方法, 为改版做准备"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
_keep = sys.stdout

P = r"D:\ubuntu_iso\ui\desktop.py"
raw = open(P, "rb").read()

enc = None
for e in ("utf-8", "gbk", "gb18030"):
    try:
        s = raw.decode(e)
        enc = e
        break
    except Exception:
        continue
print("编码 = %s   大小 %d 字节" % (enc, len(raw)))
print("首行: %r" % s.splitlines()[0])
print("前 12 行:")
for l in s.splitlines()[:12]:
    print("   " + l)

print()
print("=" * 70)
print("顶层常量/赋值")
print("=" * 70)
for m in re.finditer(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$", s, re.M):
    v = m.group(2)
    print("   %-18s = %s" % (m.group(1), v[:100]))

print()
print("=" * 70)
print("Desktop 类的方法")
print("=" * 70)
i = s.find("class Desktop")
body = s[i:]
for m in re.finditer(r"^    def (\w+)\(self([^)]*)\)", body, re.M):
    print("   def %-22s (%s" % (m.group(1), m.group(2).strip().lstrip(",")))

print()
print("=" * 70)
print("APPS 列表内容")
print("=" * 70)
j = s.find("APPS = [")
if j >= 0:
    k = s.find("\n]", j)
    print(s[j:k + 2][:2600])
