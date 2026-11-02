#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读官方工程里 i2s_transmitter / i2s_receiver 的真实参数"""
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs"
        r"\sources_1\bd\system\ip")
FILES = [("i2s_transmitter", r"system_i2s_transmitter_0\system_i2s_transmitter_0.xci"),
         ("i2s_receiver", r"system_i2s_receiver_0\system_i2s_receiver_0.xci")]

for tag, rel in FILES:
    p = BASE + "\\" + rel
    print("=" * 78)
    print("###", tag)
    try:
        j = json.load(open(p, encoding="utf-8", errors="replace"))
    except Exception as e:
        print("  不是 json:", e)
        continue

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + "/" + str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + "/%d" % i)
        else:
            ps = path
            if re.search(r"(?i)/parameters/", ps) and not re.search(
                    r"(?i)(format|usage|resolve_type|value_permission|"
                    r"value_src|is_ips_inferred|is_static_object)$", ps):
                print("   %-58s = %s" % (ps.split("/parameters/")[-1][-58:], o))
    walk(j)
