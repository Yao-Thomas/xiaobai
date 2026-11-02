#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板子上跑: 遍历 /proc/device-tree, 导出音频相关节点 (解析 phandle)"""
import os
import struct
import sys
import glob

ROOT = "/proc/device-tree"


def read(fn):
    try:
        with open(fn, "rb") as f:
            return f.read()
    except Exception:
        return None


def props(node):
    out = {}
    try:
        names = os.listdir(node)
    except Exception:
        return out
    for n in names:
        p = os.path.join(node, n)
        if os.path.isfile(p):
            out[n] = read(p)
    return out


def s(v):
    if v is None:
        return None
    return v.rstrip(b"\0").decode("utf-8", "replace")


def u32s(v):
    if not v:
        return []
    n = len(v) // 4
    return list(struct.unpack(">%dI" % n, v[:n * 4]))


# 建 phandle -> 路径 索引
idx = {}
for dirpath, dirnames, filenames in os.walk(ROOT):
    if "phandle" in filenames or "linux,phandle" in filenames:
        v = read(os.path.join(dirpath, "phandle")) or read(
            os.path.join(dirpath, "linux,phandle"))
        if v:
            idx[u32s(v)[0]] = dirpath


def path_of(ph):
    p = idx.get(ph)
    if not p:
        return "?<%d>" % ph
    return p[len(ROOT):] or "/"


want = sys.argv[1:] or ["43c50000", "43c60000", "43c70000", "43c30000", "41600000"]

for dirpath, dirnames, filenames in os.walk(ROOT):
    base = os.path.basename(dirpath)
    if not any(w in base for w in want):
        continue
    print("===== %s" % dirpath[len(ROOT):])
    for k, v in sorted(props(dirpath).items()):
        if k in ("name", "phandle", "linux,phandle"):
            continue
        if v is None:
            continue
        if k in ("compatible", "clock-names", "clock-output-names",
                 "interrupt-names", "status"):
            print("  %-26s = %r" % (k, [s(x) for x in v.split(b"\0") if x]))
        elif k in ("clocks", "xlnx,snd-pcm", "xlnx,tx", "xlnx,rx",
                   "audio-codec", "interrupt-parent"):
            vals = u32s(v)
            print("  %-26s = %s" % (k, " ".join(path_of(x) for x in vals)))
        elif len(v) <= 16:
            print("  %-26s = %s" % (k, u32s(v) if len(v) % 4 == 0 else v.hex()))
        else:
            print("  %-26s = <%d bytes>" % (k, len(v)))
    print()
