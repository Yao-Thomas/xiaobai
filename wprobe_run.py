#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wprobe_run.py —— 在他板子上跑 wprobe.py 看 wttr.in 的字段"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

PROBE = r'''
import json, urllib.request
u = "http://wttr.in/Beijing?format=j1&lang=zh"
d = json.load(urllib.request.urlopen(u, timeout=20))
cc = d["current_condition"][0]
for k in ("temp_C", "FeelsLikeC", "humidity", "weatherDesc", "lang_zh",
          "windspeedKmph", "winddir16Point", "observation_time"):
    print("%-16s: %s" % (k, cc.get(k)))
w = d["weather"][0]
print("%-16s: %s / %s" % ("max/min", w.get("maxtempC"), w.get("mintempC")))
na = d.get("nearest_area")
if na:
    print("%-16s: %s / %s" % ("area/region",
                              na[0]["areaName"][0]["value"], na[0]["region"][0]["value"]))
print("json 大小约 %d 字节" % len(json.dumps(d)))
'''


def main():
    board.HOST = "192.168.10.18"
    open(r"D:\ubuntu_iso\wprobe.py", "w", encoding="utf8").write(PROBE)
    board.put(r"D:\ubuntu_iso\wprobe.py", "/home/zynq/wprobe.py")
    broot.srun("cd /home/zynq && python3 wprobe.py", timeout=180)


main()
