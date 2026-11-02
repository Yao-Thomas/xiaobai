#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disk_tree.py —— 干净地列出正点原子资料盘结构 (只到第 3 层, 不列文件海)
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"D:\总文件夹\FPGA2026\板卡资料"
MAXDEPTH = 3


def main():
    for d in sorted(os.listdir(ROOT)):
        full = os.path.join(ROOT, d)
        if not os.path.isdir(full):
            continue
        print("[%s]" % d)
        base = full
        for r, ds, fs in os.walk(base):
            rel = os.path.relpath(r, base)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > MAXDEPTH:
                ds[:] = []
                continue
            ds.sort()
            ind = "  " * (depth + 1)
            name = os.path.basename(r) if depth else ""
            nf = len(fs)
            if depth:
                print("%s%s/   (%d 文件)" % (ind, name, nf))
            # 只在浅层列文件
            if depth <= 1:
                for f in sorted(fs)[:25]:
                    fp = os.path.join(r, f)
                    try:
                        sz = os.path.getsize(fp)
                    except Exception:
                        sz = 0
                    print("%s  %10d  %s" % (ind, sz, f))
                if len(fs) > 25:
                    print("%s  ... 还有 %d 个文件" % (ind, len(fs) - 25))
        print()


main()
