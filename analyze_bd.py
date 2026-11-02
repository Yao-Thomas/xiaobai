#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_bd.py —— 解析正点原子的 block design, 为 GPU 集成做准备"""
import json, re, os, collections

BD = r"D:\ubuntu_iso\atk_vivado_prj\vivado_prj\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"

raw = open(BD, "r", encoding="utf-8", errors="replace").read()
print("BD 文件大小: %.1f KB" % (len(raw) / 1024.0))

# 去掉可能的 JSON 头注释
m = re.search(r"\{", raw)
txt = raw[m.start():]
try:
    j = json.loads(txt)
    print("JSON 解析: ✅")
except Exception as ex:
    print("JSON 解析失败: %s" % ex)
    j = None

if not j:
    raise SystemExit(1)

print("")
print("=" * 70)
print(" 顶层键:", list(j.keys())[:12])
print("=" * 70)

design = j.get("design", {})
print("design 里的键:", list(design.keys())[:15])

# ---- 实例 ----
cells = {}
for k in ("components", "cells"):
    if k in design:
        cells = design[k]
        break
if not cells and "components" in j:
    cells = j["components"]

print("")
print("实例数: %d" % len(cells))
by_vlnv = collections.Counter()
ps = None
for name, c in cells.items():
    v = c.get("vlnv", "")
    by_vlnv[v] += 1
    if "processing_system7" in v:
        ps = name

print("")
print("---- 用到的 IP (按 vlnv) ----")
for v, n in sorted(by_vlnv.items(), key=lambda t: -t[1]):
    print("  %-52s x%d" % (v, n))

print("")
print("---- 实例名清单 ----")
for name in sorted(cells.keys()):
    print("  %s" % name)

# ---- 找 PS ----
if ps:
    print("")
    print("=" * 70)
    print(" Zynq PS 实例: %s" % ps)
    print("=" * 70)
    c = cells[ps]
    for key in ("ports", "interfaces", "pins"):
        if key in c:
            print("  %s: %d 个" % (key, len(c[key])))
            if key == "interfaces":
                for iname, iv in c[key].items():
                    print("      %-22s %s" % (iname, iv.get("vlnv", "")))
