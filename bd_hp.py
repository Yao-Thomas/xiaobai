#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bd_hp.py —— 找出 PS 的 HP 口被谁占用了, 哪个空着 (GPU 集成关键)"""
import json, re, collections

BD = r"D:\ubuntu_iso\atk_vivado_prj\vivado_prj\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"
raw = open(BD, "r", encoding="utf-8", errors="replace").read()
j = json.loads(raw[re.search(r"\{", raw).start():])
d = j["design"]

print("=" * 74)
print(" [1] design 顶层键的类型")
print("=" * 74)
for k, v in d.items():
    print("   %-18s %-8s %s" % (k, type(v).__name__,
          len(v) if hasattr(v, "__len__") else ""))

print("")
print("=" * 74)
print(" [2] 所有 components 的 interface_ports (谁连了什么)")
print("=" * 74)
for cname, c in d.get("components", {}).items():
    ip = c.get("interface_ports", {})
    if not ip:
        continue
    items = []
    for pname, pv in ip.items():
        mode = pv.get("mode", "") if isinstance(pv, dict) else ""
        items.append("%s(%s)" % (pname, mode))
    print("   %-22s : %s" % (cname, ", ".join(sorted(items))))

print("")
print("=" * 74)
print(" [3] interface_nets —— 每条网络连接了哪些引脚")
print("=" * 74)
net = d.get("interface_nets", {})
if isinstance(net, dict):
    for nname, n in sorted(net.items()):
        if not isinstance(n, dict):
            print("   %s -> %s" % (nname, str(n)[:90]))
            continue
        name = n.get("name", nname)
        pts = []
        for key in ("interface_ports", "ports", "pins"):
            v = n.get(key)
            if isinstance(v, dict):
                pts += list(v.keys())
            elif isinstance(v, list):
                pts += [str(x) for x in v]
        print("   %-30s : %s" % (name[:30], ", ".join(pts)[:120]))
else:
    print("   interface_nets 类型:", type(net))

print("")
print("=" * 74)
print(" [4] 重点: PS 的 HP 口连到哪里")
print("=" * 74)
s = json.dumps(d, ensure_ascii=False)
for hp in ("S_AXI_HP0", "S_AXI_HP1", "S_AXI_HP2", "S_AXI_HP3", "S_AXI_ACP", "M_AXI_GP0", "M_AXI_GP1"):
    n = s.count(hp)
    print("   %-12s 在 BD 中出现 %d 次 %s" % (hp, n, "✅ 有连接" if n > 1 else "⬜ 可能空闲"))
