#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
P = r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"
d = json.load(open(P, encoding="utf-8"))
c = d["design"]["components"]

hp = c["hp3_merge"]
print("hp3_merge children:", list((hp.get("components") or {}).keys()))
for k, v in (hp.get("components") or {}).items():
    print("---", k, v.get("vlnv"), v.get("xci_path"))
    s = json.dumps(v.get("parameters") or {}, ensure_ascii=False)
    for m in re.findall(r'"[A-Z_]*WIDTH[A-Z_]*":\s*\{[^}]*\}', s):
        print("      ", m)

print()
print("=== gpu_0 raw ===")
print(json.dumps(c["gpu_0"], ensure_ascii=False)[:3000])

print()
print("=== ps7_0_axi_periph children (含 gpu 的) ===")
pp = c["ps7_0_axi_periph"]
for k, v in (pp.get("components") or {}).items():
    s = json.dumps(v.get("parameters") or {}, ensure_ascii=False)
    if "gpu" in s.lower() or "m16" in k.lower() or "us" in k.lower():
        print("---", k, v.get("vlnv"))
        for m in re.findall(r'"[A-Z_]*WIDTH[A-Z_]*":\s*\{[^}]*\}', s):
            print("      ", m)

print()
print("=== nets: 连到 gpu_0 的所有 net ===")
for k, v in (d["design"]["nets"] or {}).items():
    s = json.dumps(v)
    if "gpu_0" in s:
        print(" ", k, json.dumps(v, ensure_ascii=False)[:400])
