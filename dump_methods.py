#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_methods.py —— 打印 desktop.py 里指定方法的完整源码"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

P = r"D:\ubuntu_iso\ui\desktop.py"
s = open(P, encoding="utf8").read()
lines = s.splitlines()

WANT = sys.argv[1:] or ["page_count", "goto_page", "draw_dots", "draw", "run", "_do_tap"]


def method_span(name):
    pat = re.compile(r"^    def %s\(" % re.escape(name))
    start = None
    for i, l in enumerate(lines):
        if pat.match(l):
            start = i
            break
    if start is None:
        return None
    j = start + 1
    while j < len(lines) and not re.match(r"^    def |^class |^\S", lines[j]):
        j += 1
    return start, j


for w in WANT:
    sp = method_span(w)
    print("=" * 74)
    if not sp:
        print("!! 找不到 %s" % w)
        continue
    a, b = sp
    print("### %s  (行 %d..%d)" % (w, a + 1, b))
    print("=" * 74)
    for i in range(a, b):
        print("%5d| %s" % (i + 1, lines[i]))
    print()
