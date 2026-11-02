#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_design.py —— 解开厂家 V3.7 音频章节, 看音频设计到底是什么; 并挖 DTB 声卡节点"""
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
V37 = os.path.join(BASE, "9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）")
RAR = os.path.join(V37, "4_Source_Code", "1_FPGA_Design", "ZYNQ_7020_FPGA.rar")
OUT = r"D:\ubuntu_iso\_v37_audio"

OUT2 = []


def p(*a):
    OUT2.append(" ".join(str(x) for x in a))


def main():
    p("=" * 78)
    p("一、V3.7 音频章节 37_audio_loopback 完整文件清单")
    p("=" * 78)
    r = subprocess.run([UNRAR, "lb", RAR], capture_output=True, timeout=600)
    names = [n for n in r.stdout.decode("gbk", "replace").splitlines() if n.strip()]
    p("  共 %d 项" % len(names))
    # 只列源码/约束/tcl/bd/doc, 跳过 vivado 缓存
    keep = []
    for n in names:
        low = n.lower()
        if any(s in low for s in (".cache", ".runs", ".hw", ".sim", ".ip_user_files",
                                  ".gen", "/.xil", "webtalk", ".jou", ".log", ".str")):
            continue
        keep.append(n)
    p("  过滤掉 Vivado 缓存后 %d 项:" % len(keep))
    for n in keep:
        p("     " + n)

    p()
    p("=" * 78)
    p("二、解压到本地看源码")
    p("=" * 78)
    os.makedirs(OUT, exist_ok=True)
    rr = subprocess.run([UNRAR, "x", "-o+", "-y", RAR, OUT + "\\"],
                        capture_output=True, timeout=900)
    p("  解压返回码 %d" % rr.returncode)
    got = 0
    for root, ds, fs in os.walk(OUT):
        for f in fs:
            got += 1
    p("  解出 %d 个文件" % got)

    p()
    p("=" * 78)
    p("三、看音频相关的 RTL / BD / 约束")
    p("=" * 78)
    for root, ds, fs in os.walk(OUT):
        for f in sorted(fs):
            low = f.lower()
            if not (low.endswith((".v", ".sv", ".vhd", ".xdc", ".tcl", ".bd", ".c", ".h",
                                  ".md", ".txt", ".xsa"))):
                continue
            fp = os.path.join(root, f)
            rel = fp.replace(OUT, "")
            try:
                sz = os.path.getsize(fp)
            except Exception:
                continue
            if sz < 200 or sz > 400000:
                continue
            p("  ---- %s (%d) ----" % (rel, sz))
            if low.endswith((".v", ".sv", ".xdc", ".tcl", ".c", ".h", ".md", ".txt")):
                try:
                    txt = open(fp, "rb").read().decode("gbk", "replace")
                    for line in txt.splitlines()[:70]:
                        p("      " + line)
                except Exception as e:
                    p("      (读不了 %s)" % e)

    open(r"D:\ubuntu_iso\audio_design.txt", "w", encoding="utf8").write("\n".join(OUT2))

    print("=" * 78)
    print("四、他的 DTB 里声音/音频节点")
    print("=" * 78)
    from dtbdump import parse, fmt_val
    data = open(r"D:\总文件夹\FPGA2026\_ref_boot\fit\fdt-7020.dtb", "rb").read()
    _, _, tree = parse(data)
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
