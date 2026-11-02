#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往 /dev/input/eventX 触发蜂鸣器 —— 单独验一下"""
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EV_SYN, EV_SND = 0x00, 0x12
SND_BELL, SND_TONE = 0x01, 0x02

txt = open("/proc/bus/input/devices").read()
print("=== 所有输入设备 ===")
print(txt)

cand = []
for b in txt.split("\n\n"):
    if "beep" in b.lower() or "buzzer" in b.lower():
        for ln in b.splitlines():
            if ln.startswith("H:"):
                for t in ln.split():
                    if t.startswith("event"):
                        cand.append("/dev/input/" + t)
print("蜂鸣器候选设备:", cand)

for path in cand:
    for mode, name in ((SND_TONE, "SND_TONE(1000)"), (SND_BELL, "SND_BELL")):
        try:
            fd = os.open(path, os.O_WRONLY)
            try:
                v = 1000 if mode == SND_TONE else 1
                os.write(fd, struct.pack("llHHi", 0, 0, EV_SND, mode, v))
                os.write(fd, struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))
                time.sleep(0.35)
                os.write(fd, struct.pack("llHHi", 0, 0, EV_SND, mode, 0))
                os.write(fd, struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))
                print("  %s 用 %s 写了 -> 成功" % (path, name))
            finally:
                os.close(fd)
            time.sleep(0.3)
        except Exception as e:
            print("  %s 用 %s 失败: %s" % (path, name, e))
