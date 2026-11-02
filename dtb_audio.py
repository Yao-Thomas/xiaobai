#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtb_audio.py —— 把 DTB 里音频链路彻底挖干净: codec 节点 / 声卡 / phandle 指向"""
import re
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dtbdump import parse, fmt_val

HIS = r"D:\总文件夹\FPGA2026\_ref_boot\fit\fdt-7020.dtb"
OURS = r"D:\总文件夹\FPGA2026\_boot_backup_0926_192947\system.dtb"


def build(path):
    data = open(path, "rb").read()
    _, _, tree = parse(data)
    nodes, order, stack = {}, [], []
    for depth, kind, payload in tree:
        if kind == "node":
            stack = stack[:depth]
            stack.append(payload)
            pth = "/" + "/".join(x for x in stack if x != "/")
            nodes.setdefault(pth, [])
            order.append(pth)
        elif kind == "prop":
            k, v = payload
            nodes["/" + "/".join(x for x in stack if x != "/")].append((k, v))
    return nodes, order


def main():
    n, o = build(HIS)
    print("=" * 78)
    print("一、所有含 sound/codec/audio/i2s/wm8960 的节点 (他的 DTB)")
    print("=" * 78)
    want = re.compile(r"snd|sound|codec|audio|i2s|wm8960|dummy", re.I)
    for pth in o:
        if want.search(pth):
            print("  " + pth)
            for k, v in n[pth]:
                print("        %-26s = %s" % (k, fmt_val(v)))

    print()
    print("=" * 78)
    print("二、phandle 表 (谁指向谁)")
    print("=" * 78)
    ph = {}
    for pth in o:
        for k, v in n[pth]:
            if k == "phandle" and len(v) == 4:
                ph[struct.unpack(">I", v)[0]] = pth
    for k in sorted(ph):
        print("   %3d -> %s" % (k, ph[k]))

    print()
    print("=" * 78)
    print("三、audio_formatter 引用的 audio-codec = phandle ?")
    print("=" * 78)
    for k, v in n.get("/amba_pl/audio_formatter@43c50000", []):
        if k in ("audio-codec", "clocks", "clock-names", "interrupts"):
            val = fmt_val(v)
            print("   %-16s = %s" % (k, val))
    print()
    print("   i2c@e0004000 下的设备:")
    for pth in o:
        if pth.startswith("/amba/i2c@e0004000"):
            print("     " + pth)
            for k, v in n[pth]:
                if k in ("compatible", "reg", "status", "phandle", "clock-names", "clocks"):
                    print("        %-20s = %s" % (k, fmt_val(v)))

    print()
    print("=" * 78)
    print("四、和我们的对比: 音频相关节点是否一致")
    print("=" * 78)
    on, oo = build(OURS)
    hs = sorted(p for p in o if want.search(p))
    os_ = sorted(p for p in oo if want.search(p))
    print("   他有 %d, 我们有 %d" % (len(hs), len(os_)))
    print("   只有他有: %s" % [x for x in hs if x not in os_])
    print("   只有我们有: %s" % [x for x in os_ if x not in hs])
    for pth in set(hs) & set(os_):
        dh, do = dict(n[pth]), dict(on[pth])
        for k in sorted(set(dh) | set(do)):
            if dh.get(k) != do.get(k):
                print("   [属性不同] %s :: %s" % (pth, k))
                print("        他 = %s" % (fmt_val(dh[k]) if k in dh else "(无)"))
                print("        我 = %s" % (fmt_val(do[k]) if k in do else "(无)"))


main()
