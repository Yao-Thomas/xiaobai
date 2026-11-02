#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read_hw.py —— 读硬件/设计资料 (GBK 编码), 并找解压工具"""
import io
import os
import shutil
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
XDC = os.path.join(BASE, "3_开发板原理图和硬件相关文件", "NAVIGATOR_ZYNQ_IO.xdc")


def find_tools():
    print("### 找解压工具")
    names = ["7z.exe", "7za.exe", "7zr.exe", "WinRAR.exe", "Rar.exe", "unrar.exe", "unrar",
             "bandizip.exe", "Bandizip.exe", "7z"]
    hits = []
    for n in names:
        p = shutil.which(n)
        if p:
            hits.append(p)
    for d in [r"C:\Program Files\7-Zip", r"C:\Program Files (x86)\7-Zip",
              r"C:\Program Files\WinRAR", r"C:\Program Files (x86)\WinRAR",
              r"C:\Program Files\Bandizip"]:
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().endswith(".exe"):
                    hits.append(os.path.join(d, f))
    for h in hits:
        print("   " + h)
    if not hits:
        print("   (PATH 和常见目录里都没有)")
    return hits


def main():
    find_tools()
    print()
    print("### NAVIGATOR_ZYNQ_IO.xdc")
    raw = open(XDC, "rb").read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            txt = raw.decode(enc)
            print("   (编码 %s, %d 字节, %d 行)" % (enc, len(raw), txt.count("\n")))
            break
        except Exception:
            continue
    else:
        txt = raw.decode("utf-8", "replace")
    open(r"D:\ubuntu_iso\xdc.txt", "w", encoding="utf8").write(txt)
    print(txt)


main()
