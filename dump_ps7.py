#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_ps7.py —— 探明 BD 结构并提取 PS7 的 AXI 端口配置"""
import json, re, os

BD = r"D:\ubuntu_iso\atk_vivado_prj\vivado_prj\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"
raw = open(BD, "r", encoding="utf-8", errors="replace").read()
j = json.loads(raw[re.search(r"\{", raw).start():])
d = j["design"]
cells = d["components"]

print("=" * 74)
print(" BD 顶层结构")
print("=" * 74)
for k, v in d.items():
    print("   %-18s %s (%d 项)" % (k, type(v).__name__, len(v) if hasattr(v, "__len__") else 0))

print("")
print("=" * 74)
print(" PS7 实例 (processing_system7_0) 的键")
print("=" * 74)
ps = cells["processing_system7_0"]
for k, v in ps.items():
    n = len(v) if hasattr(v, "__len__") else "-"
    print("   %-18s %s (%s)" % (k, type(v).__name__, n))

print("")
print("=" * 74)
print(" PS7 参数(前 60 个) —— 关键看 AXI 端口使能与位宽")
print("=" * 74)
params = ps.get("parameters", {})
if isinstance(params, dict):
    keys = sorted(params.keys())
    for k in keys:
        v = params[k]
        val = v.get("value") if isinstance(v, dict) else v
        print("   %-46s = %s" % (k, val))
else:
    print("   parameters 不是 dict:", type(params))
    print("   样本:", str(params)[:400])

print("")
print("=" * 74)
print(" PS7 的 interfaces / ports")
print("=" * 74)
for key in ("interfaces", "ports", "interface_ports", "pins"):
    if key in ps:
        v = ps[key]
        print("   %s (%s, %d 项):" % (key, type(v).__name__, len(v)))
        if isinstance(v, dict):
            for name, iv in list(v.items())[:40]:
                desc = ""
                if isinstance(iv, dict):
                    desc = iv.get("vlnv", "") or iv.get("direction", "") or str(list(iv.keys())[:4])
                print("       %-34s %s" % (name, desc))
        elif isinstance(v, list):
            for iv in v[:40]:
                print("       %s" % str(iv)[:120])
