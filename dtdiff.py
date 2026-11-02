#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtdiff.py —— 比较两份设备树的 amba_pl 节点, 看我们比厂商多/少了什么"""
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtbdump import parse            # noqa: E402  (它自己会包一层 stdout)

# dtbdump 在被 import 时已经重绑过 sys.stdout, 这里不要再包一次
# (再包会把底层 buffer 关掉, 报 "I/O operation on closed file")
if not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")


def nodes(path):
    _, _, tree = parse(open(path, "rb").read())
    out = []
    stack = []
    for depth, kind, payload in tree:
        if kind == "node":
            if depth < len(stack):
                stack = stack[:depth]
            stack.append(payload)
            out.append(("/" + "/".join(stack[1:]) if len(stack) > 1 else "/",
                        list(stack)))
        elif kind == "endnode":
            if depth < len(stack):
                stack = stack[:depth]
    return [p for p, _ in out]


def under(paths, root):
    return set(p for p in paths if p.startswith(root + "/") and
               p.count("/") == root.count("/") + 1)


A = r"D:\总文件夹\FPGA2026\_ref_boot\atk-7020.dtb"
B = (r"D:\总文件夹\FPGA2026_项目交接包\01_板载系统备份"
     r"\引导文件\system.dtb")

pa = nodes(A)
pb = nodes(B)
print("厂商 DTB : %d 个节点" % len(pa))
print("我们的   : %d 个节点" % len(pb))

for root in ("/amba_pl", "/amba"):
    na, nb = under(pa, root), under(pb, root)
    print()
    print("=" * 70)
    print(" %s" % root)
    print("=" * 70)
    only_b = sorted(nb - na)
    only_a = sorted(na - nb)
    print("  我们多出来的 (%d):" % len(only_b))
    for x in only_b:
        print("      + %s" % x.split("/")[-1])
    print("  厂商有我们没有的 (%d):" % len(only_a))
    for x in only_a:
        print("      - %s" % x.split("/")[-1])
    print("  两边都有 (%d):" % len(na & nb))
    for x in sorted(na & nb):
        print("      = %s" % x.split("/")[-1])
