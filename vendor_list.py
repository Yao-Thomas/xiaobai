#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor_list.py —— 列厂家源码压缩包的内容 + 出厂测试资料"""
import io
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
V37 = os.path.join(BASE, "9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）")

RARS = [
    os.path.join(BASE, "4_Source_Code", "1_FPGA_Design", "ZYNQ_7020_FPGA.rar"),
    os.path.join(BASE, "4_Source_Code", "1_FPGA_Design", "ZYNQ_7010_FPGA.rar"),
    os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux", "vivado_prj.rar"),
    os.path.join(V37, "4_Source_Code", "1_FPGA_Design", "ZYNQ_7020_FPGA.rar"),
]


def listrar(p, limit=120):
    print("=" * 78)
    print(p.replace(BASE, "..."))
    if not os.path.exists(p):
        print("   (不存在)")
        return
    print("   大小 %.1f MB" % (os.path.getsize(p) / 1e6))
    try:
        r = subprocess.run([UNRAR, "lb", p], capture_output=True, timeout=300)
        names = r.stdout.decode("gbk", "replace").splitlines()
        print("   共 %d 项" % len(names))
        for n in names[:limit]:
            print("      " + n)
        if len(names) > limit:
            print("      ... 还有 %d 项" % (len(names) - limit))
    except Exception as e:
        print("   列表失败: %s" % e)


def main():
    print("### 目录: 9_...V3.7.../4_Source_Code 结构")
    for r, ds, fs in os.walk(os.path.join(V37, "4_Source_Code")):
        rel = os.path.relpath(r, V37)
        print("   [%s]" % rel)
        for f in sorted(fs):
            fp = os.path.join(r, f)
            print("      %12d  %s" % (os.path.getsize(fp), f))
    print()
    print("### 出厂综合测试目录")
    for r, ds, fs in os.walk(os.path.join(BASE, "1_领航者ZYNQ开发板出厂综合测试")):
        for f in sorted(fs):
            fp = os.path.join(r, f)
            print("   %12d  %s" % (os.path.getsize(fp), fp.replace(BASE, "...")))
    for r, ds, fs in os.walk(os.path.join(V37, "1_领航者ZYNQ开发板出厂综合测试")):
        for f in sorted(fs):
            fp = os.path.join(r, f)
            print("   %12d  %s" % (os.path.getsize(fp), fp.replace(BASE, "...")))
    print()
    for p in RARS:
        listrar(p)


main()
