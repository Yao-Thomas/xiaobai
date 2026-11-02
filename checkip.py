#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkip.py —— 检查 component.xml 的接口参数与端口位宽"""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

for tag, path in (("NEW", r"D:\ubuntu_iso\gpu_ip\component.xml"),
                  ("OLD", r"D:\ubuntu_iso\gpu_ip2\component.xml")):
    try:
        t = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("%s  %s  打不开: %s" % (tag, path, e))
        continue
    print("=" * 60)
    print("%s  %s   (%d 字节)" % (tag, path, len(t)))
    print("=" * 60)
    for pat in ("ASSOCIATED_BUSIF", "ASSOCIATED_RESET", "POLARITY"):
        for m in re.finditer(r"<spirit:name>%s</spirit:name>\s*<spirit:value[^>]*>([^<]*)<" % pat, t):
            print("   %-18s = %s" % (pat, m.group(1)))
    # 端口位宽
    for port in ("m_axi_wdata", "m_axi_wstrb", "m_axi_awsize", "m_axi_awlen"):
        m = re.search(r"<spirit:name>%s</spirit:name>(.{0,400}?)</spirit:port>" % port, t, re.S)
        if m:
            seg = m.group(1)
            left = re.search(r"<spirit:left>(\d+)</spirit:left>", seg)
            right = re.search(r"<spirit:right>(\d+)</spirit:right>", seg)
            drv = re.search(r"<spirit:driverValue>([^<]*)</spirit:driverValue>", seg)
            w = (int(left.group(1)) - int(right.group(1)) + 1) if (left and right) else "?"
            print("   %-14s 位宽=%-4s (left=%s right=%s)" %
                  (port, w, left.group(1) if left else "?", right.group(1) if right else "?"))
        else:
            print("   %-14s 未找到" % port)
    print()
