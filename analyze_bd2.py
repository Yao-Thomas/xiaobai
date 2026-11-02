#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_bd2.py —— 深挖 AXI 连接结构: PS 端口 / 互联 / 时钟 / 地址"""
import json, re, collections

BD = r"D:\ubuntu_iso\atk_vivado_prj\vivado_prj\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"
raw = open(BD, "r", encoding="utf-8", errors="replace").read()
j = json.loads(raw[re.search(r"\{", raw).start():])
d = j["design"]
cells = d["components"]
nets = d.get("nets", {})
ifnets = d.get("interface_nets", {})
addr = d.get("addressing", {})

def comp(name):
    return cells.get(name, {})

print("=" * 72)
print(" [1] Zynq PS 的所有接口")
print("=" * 72)
ps = comp("processing_system7_0")
for iname, iv in ps.get("interfaces", {}).items():
    print("   %-28s %s" % (iname, iv.get("vlnv", "")))

print("")
print("=" * 72)
print(" [2] AXI 互联 (ps7_0_axi_periph) 的从口连接情况")
print("=" * 72)
ic = comp("ps7_0_axi_periph")
print("   接口:")
for iname, iv in ic.get("interfaces", {}).items():
    print("      %-18s %s" % (iname, iv.get("vlnv", "").split(":")[-2:]))
print("   参数(端口数):")
for p, pv in ic.get("parameters", {}).items():
    if "NUM" in p or "FREQ" in p:
        print("      %-40s = %s" % (p, pv.get("value", "")))

print("")
print("=" * 72)
print(" [3] 接口连接 (interface_nets) —— GPU 要接的地方")
print("=" * 72)
for nname, n in sorted(ifnets.items()):
    pts = []
    for pin in n.get("interface_ports", {}).keys():
        pts.append(pin)
    for pk, pv in n.get("interface_ports", {}).items():
        pass
    name = n.get("name", nname)
    print("   %-34s : %s" % (name, ", ".join(sorted(pts))[:130]))

print("")
print("=" * 72)
print(" [4] 时钟 / 复位网络")
print("=" * 72)
for nname, n in sorted(nets.items()):
    nm = n.get("name", nname)
    if any(k in nm.lower() for k in ("clk", "reset", "rst", "clock")):
        pts = list(n.get("ports", {}).keys())
        print("   %-34s : %s" % (nm, ", ".join(sorted(pts))[:120]))

print("")
print("=" * 72)
print(" [5] 已分配的地址空间")
print("=" * 72)
for seg, sv in sorted(addr.items()):
    print("   %-52s -> %s" % (seg[:52], sv.get("offset", "")))
