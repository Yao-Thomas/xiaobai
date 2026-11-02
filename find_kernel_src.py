#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_kernel_src.py —— 资料盘里到底有没有内核源码/工具链 (决定音频走哪条路)"""
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
EL = os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux")

RARS = [
    os.path.join(EL, "资源文件.rar"),
    os.path.join(EL, "vivado_prj.rar"),
    os.path.join(BASE, "9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）",
                 "4_Source_Code", "3_Embedded_Linux", "资源文件.rar"),
]
KW = re.compile(r"linux-xlnx|kernel|Module\.symvers|\.config|Makefile$|petalinux|"
                r"sdk|toolchain|gcc|\.bb$|recipes|linux/", re.I)


def main():
    print("### 目录里还有什么")
    for r, d, f in os.walk(EL):
        for x in sorted(f):
            p = os.path.join(r, x)
            print("   %12d  %s" % (os.path.getsize(p), p.replace(BASE, "...")))

    for p in RARS:
        print("=" * 74)
        print(p.replace(BASE, "..."))
        if not os.path.exists(p):
            print("   (不存在)")
            continue
        print("   %.0f MB" % (os.path.getsize(p) / 1e6))
        try:
            r = subprocess.run([UNRAR, "lb", p], capture_output=True, timeout=1800)
            names = [n for n in r.stdout.decode("gbk", "replace").splitlines() if n.strip()]
            print("   共 %d 项" % len(names))
            tops = {}
            for n in names:
                t = n.replace("/", "\\").split("\\")[0]
                tops[t] = tops.get(t, 0) + 1
            for t in sorted(tops)[:40]:
                print("      顶层 %-50s (%d)" % (t, tops[t]))
            hits = [n for n in names if KW.search(n)]
            print("   ★ 命中 kernel/toolchain 关键词 %d 项, 前 40:" % len(hits))
            for n in hits[:40]:
                print("      " + n)
        except Exception as e:
            print("   打不开: %s" % e)


main()
