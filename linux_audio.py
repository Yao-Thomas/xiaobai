#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""linux_audio.py —— 内核里的音频/codec 配置 + 厂家 Linux 驱动例程章节"""
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
_out = sys.stdout            # 抓住引用, 防止被 GC 关掉底层 buffer

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"


def main():
    print("=" * 78)
    print("一、内核 config 里的音频/codec 项 (他的内核)")
    print("=" * 78)
    for f, tag in ((r"D:\ubuntu_iso\cfg_B.txt", "他的 kernel"),
                   (r"D:\ubuntu_iso\cfg_C.txt", "我们的 zImage")):
        if not os.path.exists(f):
            print("   (%s 不存在)" % f)
            continue
        print("--- %s ---" % tag)
        txt = open(f, encoding="utf8", errors="replace").read()
        for line in txt.splitlines():
            if re.search(r"SND_SOC_WM8960|SND_SOC_ZYNQ|SND_SOC_XILINX|SND_SIMPLE_CARD|"
                         r"SND_SOC_I2S|SND_SOC_XLNX|SOUND=|SND=|SND_SOC=|SND_ALSA|"
                         r"SND_SOC_GENERIC|SND_SOC_ADAU|SND_SOC_SSM", line):
                print("   " + line)

    print()
    print("=" * 78)
    print("二、厂家 Linux 驱动例程章节 (= 板子的 Linux 功能清册)")
    print("=" * 78)
    rar = os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux", "Linux驱动例程.rar")
    print("   %s  (%.0f MB)" % (rar, os.path.getsize(rar) / 1e6))
    r = subprocess.run([UNRAR, "lb", rar], capture_output=True, timeout=1800)
    names = [n for n in r.stdout.decode("gbk", "replace").splitlines() if n.strip()]
    print("   共 %d 项" % len(names))
    roots = {}
    for n in names:
        parts = n.replace("/", "\\").split("\\")
        if len(parts) >= 2:
            roots.setdefault(parts[0] + "|" + parts[1], 0)
            roots[parts[0] + "|" + parts[1]] += 1
    for k in sorted(roots):
        print("      %-60s (%d)" % (k, roots[k]))

    print()
    print("=" * 78)
    print("三、文件名里带 audio/sound/wm8960/alsa/player/music 的条目")
    print("=" * 78)
    for n in names:
        if re.search(r"audio|sound|wm8960|alsa|player|music|aplay|arecord|codec|i2s|"
                     r"音乐|音频|播放|录音", n, re.I):
            print("      " + n)


main()
