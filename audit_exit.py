#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审一遍所有 App：怎么退出？有没有"返回桌面"的判定？"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
# 退出相关的关键字
KEYS = ("back_hit", "退出", "返回桌面", "回桌面", "quit", "EXIT", "exit(",
        "sys.exit", "ESC", "ESCAPE")


def main():
    for fn in sorted(os.listdir(D)):
        if not fn.startswith("apps_") or not fn.endswith(".py"):
            continue
        src = open(os.path.join(D, fn), encoding="utf-8").read()
        lines = src.splitlines()
        hits = []
        for i, ln in enumerate(lines, 1):
            for k in KEYS:
                if k in ln:
                    hits.append((i, k, ln.strip()[:110]))
                    break
        # 顶层 run() 的 while 循环体
        m = re.search(r"^def run\(scr, touch\):(.*)$", src, re.M | re.S)
        has_while_true = bool(re.search(r"while True:", src))
        print("=" * 78)
        print("%-20s  行数=%-5d while True=%s  退出相关命中=%d"
              % (fn, len(lines), has_while_true, len(hits)))
        for i, k, t in hits[:8]:
            print("   %4d [%s] %s" % (i, k, t))


if __name__ == "__main__":
    main()
