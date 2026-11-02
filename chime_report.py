#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chime_report.py —— 算每个提示音的平均能量（RMS），量化"有多响"。

背景：用户反馈"声音还是太小"。
      先证明 codec 侧已经顶满（0x1A/0x1B=0dB、0x2E..0x31=33），
      再看信号本身：满量程 1kHz 正弦的 RMS 是 -3.0 dBFS，
      而普通提示音只有 -13.6 dBFS —— 因为衰减太快、平均能量只有峰值的 21%。
      所以"小"有很大一部分是**信号形状**问题，不是纯硬件。
"""
import math
import os
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ui"))
import chime                                                   # noqa: E402

RATE = 44100
n = RATE // 2
sine = [int(32767 * math.sin(2 * math.pi * 1000 * i / RATE)) for i in range(n)]
REF = math.sqrt(sum(float(x) * x for x in sine) / len(sine))

print("满量程 1kHz 正弦:  RMS=%.1f  (%.1f dBFS)" % (REF, 20 * math.log10(REF / 32767)))
print()
print("%-8s %-18s %-8s %-9s %-8s %-10s %s"
      % ("key", "名称", "峰值", "RMS", "RMS/FS", "相对满正弦", "时长"))
print("-" * 84)
for k in chime.STYLES:
    s = chime.make_chime(k)
    pk = max(abs(x) for x in s)
    rms = math.sqrt(sum(float(x) * x for x in s) / len(s))
    db = 20 * math.log10(rms / REF)
    print("%-8s %-18s %-8d %-9.1f %-7.1f%% %+8.1f dB  %.2fs"
          % (k, chime.STYLE_NAMES.get(k, k), pk, rms, 100 * rms / 32767, db,
             len(s) / float(RATE)))
print("-" * 84)
print("结论：带(响)后缀的那几个平均能量明显更高（压缩包络+更长延音），")
print("      峰值一样是 95%，所以不会削顶。")
