#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_toolchain.py —— 找交叉编译器 / Module.symvers / PetaLinux 工程内容"""
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"

# 1) 本机有没有交叉编译器
print("### 本机上的交叉工具链")
roots = [r"D:\Xilinx", r"C:\Xilinx", "D:\\", r"C:\Program Files\Xilinx",
         os.path.join(BASE, "6_常用软件")]
pat = re.compile(r"arm-(xilinx|none|linux)[\w-]*-gcc(\.exe)?$", re.I)
found = []
for root in roots:
    if not os.path.isdir(root):
        continue
    depth0 = root.rstrip("\\").count("\\")
    for r, ds, fs in os.walk(root):
        if r.count("\\") - depth0 > 4:
            ds[:] = []
            continue
        for f in fs:
            if pat.match(f):
                found.append(os.path.join(r, f))
        if len(found) > 30:
            break
    if found:
        break
for f in found[:20]:
    print("   " + f)
if not found:
    print("   (没找到 arm-*-gcc)")

print()
print("### 找 aarch64 / arm 的 toolchain 目录")
for root in [r"D:\Xilinx", r"C:\Xilinx"]:
    if not os.path.isdir(root):
        continue
    for r, ds, fs in os.walk(root):
        if r.count("\\") - root.count("\\") > 3:
            ds[:] = []
            continue
        b = os.path.basename(r).lower()
        if "gnu" in b and ("aarch" in b or "arm" in b):
            print("   " + r)

print()
print("### zynq_petalinux.rar 里有什么 (找 SDK / Module.symvers / 已编译内核)")
p = os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux", "zynq_petalinux.rar")
print("   %s  (%.0f MB)" % (p, os.path.getsize(p) / 1e6))
try:
    r = subprocess.run([UNRAR, "lb", p], capture_output=True, timeout=1800)
    names = [n for n in r.stdout.decode("gbk", "replace").splitlines() if n.strip()]
    print("   共 %d 项" % len(names))
    tops = {}
    for n in names:
        t = "\\".join(n.replace("/", "\\").split("\\")[:3])
        tops[t] = tops.get(t, 0) + 1
    for t in sorted(tops)[:50]:
        print("      %-70s (%d)" % (t, tops[t]))
    for kw in ("symvers", "sdk.sh", "zImage", "toolchain", "sysroot", "sdk/"):
        h = [n for n in names if kw.lower() in n.lower()]
        print("   ★ '%s' 命中 %d 项" % (kw, len(h)))
        for n in h[:6]:
            print("        " + n)
except Exception as e:
    print("   打不开: %s" % e)
