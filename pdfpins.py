#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdfpins.py —— 用坐标把原理图里的连接器引脚号和网络名配对

用法: python pdfpins.py <pdf> <页码(1起)> <连接器位号>
"""
import io
import re
import sys

import fitz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main():
    path, page, ref = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    doc = fitz.open(path)
    pg = doc[page - 1]
    words = pg.get_text("words")          # (x0,y0,x1,y1,text,block,line,word)
    print("第 %d 页 共 %d 个词语" % (page, len(words)))

    # 找连接器位号的坐标
    refw = [w for w in words if w[4].upper() == ref.upper()]
    if not refw:
        print("找不到位号 %s" % ref)
        return
    rx, ry = refw[0][0], refw[0][1]
    print("位号 %s 在 (%.1f, %.1f)" % (ref, rx, ry))

    # 取以位号为中心的一块区域里的词
    R = 260.0
    near = [w for w in words
            if abs(w[0] - rx) < R and abs(w[1] - ry) < R]
    near.sort(key=lambda w: (round(w[1] / 8), w[0]))

    # 找纯数字 (引脚号)
    pins = []
    for w in near:
        t = w[4].strip()
        if re.fullmatch(r"\d{1,2}", t):
            pins.append((int(t), w[0], w[1]))
    print("附近找到的引脚号: %s" % sorted(p for p, _, _ in pins))

    # 对每个引脚号, 找它附近(右边或左边)的网络名
    nets = [w for w in near
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_+/.\-]{1,20}", w[4])]
    print()
    print("%-6s %-24s %s" % ("引脚", "网络名", "(dx, dy)"))
    for p, px, py in sorted(pins):
        best, bd = None, 1e9
        for w in nets:
            if w[4].upper() == ref.upper():
                continue
            dx = w[0] - px
            dy = w[1] - py
            if abs(dy) > 12:
                continue
            d = abs(dx)
            if d < bd and d < 220:
                bd, best = d, w
        if best:
            print("%-6d %-24s (%.0f, %.0f)" % (p, best[4], best[0] - px, best[1] - py))
        else:
            print("%-6d %-24s" % (p, "(没找到)"))


main()
