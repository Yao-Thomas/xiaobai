#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bdpeek.py —— 直接解析 system.bd(JSON), 看 GPU 和 hp3_merge 的接口/宽度/net"""
import json, sys, io, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

P = r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"
d = json.load(open(P, encoding="utf-8"))
des = d["design"]

cells = des.get("bd_cells", {})
print("=== 所有 cell (name -> vlnv) ===")
for k, v in sorted(cells.items()):
    vl = v.get("vlnv", "")
    print("  %-34s %s" % (k, vl))

def dump_cell(name):
    v = cells.get(name)
    if not v:
        print("  (找不到 %s)" % name); return
    print("\n=== cell %s ===" % name)
    print("  vlnv: %s" % v.get("vlnv"))
    for p in v.get("parameters", {}).get("parameters", []) or []:
        nm = p.get("name", "")
        if re.search(r"WIDTH|PROTOCOL|NUM_|FREQ|DATA", nm):
            print("    %-40s %s" % (nm, p.get("value")))
    for p in (v.get("parameters") or {}).get("model_parameters", []) or []:
        nm = p.get("name", "")
        if re.search(r"WIDTH|PROTOCOL|NUM_|DATA", nm):
            print("   [model] %-34s %s" % (nm, p.get("value")))
    print("  -- 接口 pin --")
    for p in v.get("interface_ports", []) or []:
        print("    %-28s mode=%-6s %s" % (p.get("name"), p.get("mode"), p.get("vlnv", "")))
    print("  -- 普通 pin (前40) --")
    pins = v.get("ports", []) or []
    for p in pins[:40]:
        print("    %-28s %s" % (p.get("name"), p.get("direction", "")))
    if len(pins) > 40:
        print("    ... 共 %d 个 pin" % len(pins))

for n in ("gpu_0", "hp3_merge", "audio", "ps7_0_axi_periph", "processing_system7_0"):
    dump_cell(n)

print("\n=== 接口 net (只看涉及 gpu_0 / hp3_merge 的) ===")
for k, v in (des.get("interface_nets") or {}).items():
    nm = v.get("name", k)
    pns = v.get("interface_ports", []) or []
    txt = " ".join(p if isinstance(p, str) else str(p) for p in pns)
    if "gpu_0" in nm or "hp3_merge" in nm or "gpu_0" in txt or "hp3_merge" in txt:
        print("  %-46s -> %s" % (nm, pns))

print("\n=== 地址段 (gpu 相关) ===")
for k, v in (des.get("addressing") or {}).items():
    s = json.dumps(v)
    if "gpu_0" in s:
        print("  %s: %s" % (k, json.dumps(v, ensure_ascii=False)[:600]))
