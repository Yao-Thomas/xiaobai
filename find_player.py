#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_player.py —— 找出"音乐播放"到底在哪: 出厂系统镜像 / Qt 工程 / 驱动例程"""
import os
import re
import subprocess
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
V37 = os.path.join(BASE, "9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）")

ZIPS = [
    os.path.join(V37, "1_领航者ZYNQ开发板出厂综合测试", "IMG", "Navigator_3.7_user.zip"),
    os.path.join(BASE, "4_Source_Code", "6_Embedded_Qt_Design.zip"),
]
RARS = [
    os.path.join(BASE, "1_领航者ZYNQ开发板出厂综合测试", "IMG", "Navigator.rar"),
]

KW = re.compile(r"music|player|audio|sound|mp3|wav|aplay|音乐|播放|音频|录音|wm8960|alsa|qt",
                re.IGNORECASE)


def show_zip(p, limit=60):
    print("=" * 78)
    print(p.replace(BASE, "..."))
    if not os.path.exists(p):
        print("   (不存在)")
        return
    print("   %.0f MB" % (os.path.getsize(p) / 1e6))
    try:
        z = zipfile.ZipFile(p)
        infos = z.infolist()
        print("   共 %d 项" % len(infos))
        # 顶层
        tops = {}
        for i in infos:
            t = i.filename.replace("\\", "/").split("/")[0]
            tops[t] = tops.get(t, 0) + 1
        print("   顶层:")
        for t in sorted(tops):
            print("      %-50s (%d)" % (t, tops[t]))
        hits = [i for i in infos if KW.search(i.filename)]
        print("   命中关键词 %d 项, 前 %d:" % (len(hits), limit))
        for i in hits[:limit]:
            print("      %12d  %s" % (i.file_size, i.filename))
    except Exception as e:
        print("   打不开: %s" % e)


def show_rar(p, limit=60):
    print("=" * 78)
    print(p.replace(BASE, "..."))
    if not os.path.exists(p):
        print("   (不存在)")
        return
    print("   %.0f MB" % (os.path.getsize(p) / 1e6))
    try:
        r = subprocess.run([UNRAR, "lb", p], capture_output=True, timeout=900)
        names = [n for n in r.stdout.decode("gbk", "replace").splitlines() if n.strip()]
        print("   共 %d 项" % len(names))
        tops = {}
        for n in names:
            t = n.replace("/", "\\").split("\\")[0]
            tops[t] = tops.get(t, 0) + 1
        for t in sorted(tops):
            print("      %-50s (%d)" % (t, tops[t]))
        hits = [n for n in names if KW.search(n)]
        print("   命中关键词 %d 项, 前 %d:" % (len(hits), limit))
        for n in hits[:limit]:
            print("      " + n)
    except Exception as e:
        print("   打不开: %s" % e)


def main():
    for p in ZIPS:
        show_zip(p)
    for p in RARS:
        show_rar(p)


main()
