#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor_chapters.py —— 从厂家源码包里抽出"章节名"= 板子功能清册; 再挖 DTB 的声音节点"""
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
V37 = os.path.join(BASE, "9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）")

TARGETS = [
    ("FPGA教程工程(主)", os.path.join(BASE, "4_Source_Code", "1_FPGA_Design", "ZYNQ_7020_FPGA.rar")),
    ("V3.7 FPGA工程", os.path.join(V37, "4_Source_Code", "1_FPGA_Design", "ZYNQ_7020_FPGA.rar")),
    ("Embedded Linux vivado_prj", os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux", "vivado_prj.rar")),
]


def chapters(path, top="ZYNQ_7020_FPGA"):
    r = subprocess.run([UNRAR, "lb", path], capture_output=True, timeout=1200)
    names = r.stdout.decode("gbk", "replace").splitlines()
    roots = {}
    for n in names:
        n = n.replace("/", "\\")
        parts = n.split("\\")
        if len(parts) < 2:
            continue
        key = parts[1]
        roots.setdefault(key, 0)
        roots[key] += 1
    return roots, len(names)


def main():
    for tag, p in TARGETS:
        print("=" * 78)
        print("%s : %s" % (tag, p.replace(BASE, "...")))
        if not os.path.exists(p):
            print("   (不存在)")
            continue
        print("   文件 %.1f MB" % (os.path.getsize(p) / 1e6))
        ch, tot = chapters(p)
        print("   共 %d 项, 顶层章节 %d 个:" % (tot, len(ch)))
        for k in sorted(ch):
            print("      %-42s (%d 项)" % (k, ch[k]))
        print()

    print("=" * 78)
    print("他的 DTB 里所有带 sound/codec/i2s/audio 的节点 + 声音卡")
    from dtbdump import parse, fmt_val
    data = open(r"D:\总文件夹\FPGA2026\_ref_boot\fit\fdt-7020.dtb", "rb").read()
    total, ver, tree = parse(data)
    stack = []
    want = re.compile(r"snd|sound|audio|codec|wm8960|i2s|dummy|formatter", re.I)
    for depth, kind, payload in tree:
        if kind == "node":
            stack = stack[:depth]
            stack.append(payload)
            path = "/" + "/".join(x for x in stack if x != "/")
            if want.search(path):
                print("  " + path)
        elif kind == "prop":
            path = "/" + "/".join(x for x in stack if x != "/")
            if want.search(path):
                k, v = payload
                print("        %-24s = %s" % (k, fmt_val(v)))


main()
