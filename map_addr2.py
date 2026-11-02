#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map_addr2.py —— 正确解析 block design 的地址 -> 从设备名 对应关系

上一版没拿到名字（都是 "?"）。BD 里地址信息在
  design.addressing.<master_path>.<spaces 或 address_space>
每个段的 key 就是 segment 名，通常含从设备实例名。
"""
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BD = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs"
      r"\sources_1\bd\system\system.bd")

raw = open(BD, encoding="utf-8", errors="replace").read()
d = json.loads(raw)
des = d["design"]

print("=" * 94)
print("block design 里的实例（components 顶层）")
print("=" * 94)
comps = des.get("components", {})
for name, c in sorted(comps.items()):
    vlnv = c.get("vlnv", "")
    xci = c.get("xci_name", "")
    print("  %-32s %-52s %s" % (name, vlnv[:52], xci))
print()

print("=" * 94)
print("地址映射（从 addressing 段挖）")
print("=" * 94)

addr = des.get("addressing", {})


def walk_spaces(node, path=""):
    """递归找所有含 offset 的段"""
    out = []
    if isinstance(node, dict):
        if "offset" in node and isinstance(node.get("offset"), str):
            seg = node.get("space") or node.get("segment") or path
            out.append((node.get("offset"), node.get("range", "-"), seg))
        for k, v in node.items():
            out += walk_spaces(v, path + "/" + str(k) if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += walk_spaces(v, path + "[%d]" % i)
    return out


rows = []
for master, spaces in addr.items():
    for off, rng, seg in walk_spaces(spaces):
        rows.append((off, rng, master, seg))


def k(r):
    try:
        return int(r[0], 16)
    except Exception:
        return 0


rows.sort(key=k)
seen = set()
for off, rng, master, seg in rows:
    key = (off, seg)
    if key in seen:
        continue
    seen.add(key)
    mark = ""
    if off.lower() in ("0x43c00000", "0x43c10000"):
        mark = "  ★★ CNN 目标地址"
    elif off.lower() == "0x43cc0000":
        mark = "  ← 示波器"
    print("  %-12s %-8s %-30s %s%s" % (off, rng, str(master)[-28:], str(seg)[:34], mark))

print()
print("=" * 94)
print("如果上面还是没有从设备名，直接把 addressing 段的原文打出来")
print("=" * 94)
s = json.dumps(addr, ensure_ascii=False)
print("  长度 %d 字节" % len(s))
print("  " + s[:2500])
