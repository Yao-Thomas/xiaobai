#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qt_demo.py —— 解开厂家 Qt 例程, 找出播放器/音乐相关工程; 再扫出厂镜像里的字串"""
import os
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
QTZIP = os.path.join(BASE, "4_Source_Code", "6_Embedded_Qt_Design.zip")
OUT = r"D:\ubuntu_iso\_qt"
V37IMG = os.path.join(BASE, "9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）",
                      "1_领航者ZYNQ开发板出厂综合测试", "IMG", "Navigator_3.7_user.zip")

KW = re.compile(r"music|player|audio|sound|mp3|wav|音乐|播放|音频|录音|video|media", re.I)


def qi(p, name, outdir):
    outer = zipfile.ZipFile(p)
    inner = outer.read(name)
    open(outdir + r"\_inner.zip", "wb").write(inner)
    return zipfile.ZipFile(outdir + r"\_inner.zip")


def main():
    os.makedirs(OUT, exist_ok=True)
    print("=" * 78)
    print("一、厂家 Qt 例程 (Qt例程.zip) 内容")
    print("=" * 78)
    z = qi(QTZIP, "Qt例程.zip", OUT)
    infos = z.infolist()
    print("   共 %d 项" % len(infos))
    tops = {}
    for i in infos:
        t = i.filename.replace("\\", "/").split("/")
        key = t[0] if len(t) > 1 else i.filename
        tops[key] = tops.get(key, 0) + 1
    for t in sorted(tops):
        print("      %-56s (%d)" % (t, tops[t]))
    print()
    hits = sorted(set(
        i.filename.replace("\\", "/").split("/")[1] if len(i.filename.replace("\\", "/").split("/")) > 1
        else i.filename for i in infos if KW.search(i.filename)))
    print("   命中 music/player/audio/media 的顶层条目 (%d):" % len(hits))
    for h in hits:
        print("      " + h)
    print()
    print("   .pro / main.cpp / 源码文件前 40 个:")
    for i in infos:
        if i.filename.lower().endswith((".pro", "main.cpp", ".ui")):
            print("      %12d  %s" % (i.file_size, i.filename))
            if i.filename.count("/") > 1:
                pass

    print()
    print("=" * 78)
    print("二、出厂镜像 Navigator_3.7_user.img 里的可执行/脚本名 (字串扫描)")
    print("=" * 78)
    zz = zipfile.ZipFile(V37IMG)
    nm = zz.namelist()[0]
    print("   镜像: %s  %.0f MB" % (nm, zz.getinfo(nm).file_size / 1e6))
    pat = re.compile(rb"[/\w.\-]{4,80}(music|player|audio|sound|mp3|wav|aplay|arecord)"
                     rb"[/\w.\-]{0,60}", re.I)
    seen = set()
    with zz.open(nm) as f:
        chunk = b""
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            data = chunk + b
            for m in pat.finditer(data):
                s = m.group(0).decode("latin1")
                if s not in seen:
                    seen.add(s)
            chunk = data[-200:]
    print("   命中 %d 条不同字串, 前 120:" % len(seen))
    for s in sorted(seen)[:120]:
        print("      " + s)


main()
