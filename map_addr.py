#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map_addr.py —— 把主工程 block design 的地址映射和 AXI 从设备对应起来

目的：查清 0x43C00000 / 0x43C10000 是不是空的（CNN 加速器要用这两个地址）
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

d = json.load(open(BD, encoding="utf-8", errors="replace"))
des = d["design"]

print("=" * 90)
print("主工程地址映射：offset -> 从设备")
print("=" * 90)

# addressing 段
addr = des.get("addressing", {})
rows = []
for master, spaces in addr.items():
    if isinstance(spaces, dict):
        for seg, info in spaces.items():
            if isinstance(info, dict):
                off = info.get("offset")
                rng = info.get("range")
                if off:
                    rows.append((off, rng, master, seg))
    elif isinstance(spaces, list):
        for info in spaces:
            off = info.get("offset")
            seg = info.get("space") or info.get("segment") or "?"
            rows.append((off, info.get("range"), master, seg))

# 有些 BD 把地址放在 master 的 "address_space" 里，扫一遍兜底
if not rows:
    txt = json.dumps(des, ensure_ascii=False)
    for m in re.finditer(
            r'"offset"\s*:\s*"([^"]+)"[^}]*?"range"\s*:\s*"([^"]+)"', txt):
        rows.append((m.group(1), m.group(2), "?", "?"))

def key(r):
    try:
        return int(r[0], 16)
    except Exception:
        return 0

rows.sort(key=key)
print("  %-12s %-12s %-32s %s" % ("offset", "range", "master", "segment"))
print("  " + "-" * 84)
for off, rng, master, seg in rows:
    mark = ""
    if off.lower() in ("0x43c00000", "0x43c10000"):
        mark = "   ★★ CNN 想用这个地址！"
    if off.lower() == "0x43cc0000":
        mark = "   ← 示波器 scope_cap_axi"
    print("  %-12s %-12s %-32s %s%s"
          % (off, rng or "-", str(master)[:32], str(seg)[:24], mark))

print()
print("=" * 90)
print("判读")
print("=" * 90)
used = set(r[0].lower() for r in rows)
for a in ("0x43c00000", "0x43c10000"):
    if a in used:
        print("  %s 已被占用 -> 需要给 CNN 另分配地址，或先移除占用者" % a)
    else:
        print("  %s 空闲 ✓ CNN 可以直接用" % a)
print("  %s (示波器)   %s" % ("0x43cc0000",
      "已占用" if "0x43cc0000" in used else "空闲"))
print()
print("  AXI 从设备总数: %d" % len(rows))
