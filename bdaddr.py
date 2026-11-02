#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bdaddr.py -- compare address-space segments of audio/PS between the
   backup BD (1-byte GPU) and the new BD (64-bit GPU)"""
import json, sys, io, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PATHS = [
    ("OLD(1byte)", r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd.bak_1byte"),
    ("NEW(64bit)", r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"),
]

def segments(d, path=""):
    """recursively collect address spaces -> segments"""
    out = []
    if isinstance(d, dict):
        if "address_spaces" in d:
            for asname, asv in d["address_spaces"].items():
                segs = (asv or {}).get("segments", {}) or {}
                for sname, sv in segs.items():
                    out.append((path + "/" + asname, sname, sv))
        for k, v in d.items():
            if k == "address_spaces":
                continue
            out += segments(v, path + "/" + k)
    return out

for tag, p in PATHS:
    try:
        d = json.load(open(p, encoding="utf-8"))
    except OSError as e:
        print("%s: cannot open %s" % (tag, e))
        continue
    print("=" * 70)
    print("%s   %s" % (tag, p))
    print("=" * 70)
    segs = segments(d["design"].get("addressing", {}))
    seen = {}
    for aspace, sname, sv in segs:
        # trim the /addressing prefix noise
        a = re.sub(r"^/+", "/", aspace)
        if "audio" in a or "gpu" in a:
            key = (a, sname)
            if key in seen:
                continue
            seen[key] = 1
            if isinstance(sv, dict):
                print("  %-58s %-34s off=%s range=%s" %
                      (a, sname, sv.get("offset"), sv.get("range")))
            else:
                print("  %-58s %-34s %s" % (a, sname, sv))
    if not seen:
        print("  (no audio/gpu segments found)")
    print()
