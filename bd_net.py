#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bd_net.py —— 正经遍历 block design JSON，找 aud_bclk 所在网络的端点

BD 里网络的结构大致是：
    "nets": { "<net名>": { "ports": [...], "pins": [...] } }
或者连接信息在 "interface_ports" / 各 instance 的 "pins" 里。

这个脚本递归找出含 "aud_bclk" 的对象，打印它的全部引用。
"""
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BD = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs"
      r"\sources_1\bd\system\system.bd")

d = json.load(open(BD, encoding="utf-8", errors="replace"))
print("=" * 84)
print("block design 顶层键")
print("=" * 84)
for k in sorted(d.keys()):
    v = d[k]
    print("  %-22s %s" % (k, type(v).__name__ +
                          ("(%d)" % len(v) if isinstance(v, (dict, list)) else "")))
print()

design = d.get("design", {})
if isinstance(design, dict):
    print("design 下的键:", sorted(design.keys()))
    print()

TARGETS = ["aud_bclk", "aud_daclrc", "aud_adclrc", "aud_dacdat", "aud_mclk"]


def walk(obj, path=""):
    """递归找含目标名字的对象"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + "[%d]" % i)
    else:
        if isinstance(obj, str):
            for t in TARGETS:
                if t in obj:
                    yield (path, obj)


print("=" * 84)
print("所有提到 aud_* 的位置（路径 -> 值）")
print("=" * 84)
hits = list(walk(d))
seen = set()
for path, val in hits:
    # 去掉数组下标，聚合成模式
    key = (path.split("[")[0], val)
    if key in seen:
        continue
    seen.add(key)
    print("  %-70s = %s" % (path[:70], val[:60]))
print()
print("  共 %d 条（去重后 %d）" % (len(hits), len(seen)))
print()

# 找 nets
nets = None
for k in ("nets",):
    if k in d:
        nets = d[k]
if nets is None and "design" in d:
    nets = d["design"].get("nets")
if nets:
    print("=" * 84)
    print("含 aud_bclk 的网络")
    print("=" * 84)
    for nname, net in nets.items():
        s = json.dumps(net, ensure_ascii=False)
        if "aud_bclk" in s or "aud_daclrc" in s or "aud_adclrc" in s:
            print("  网络名: %s" % nname)
            print("    %s" % s[:600])
            print()
else:
    print("（没找到顶层 nets，可能在 design 里）")
