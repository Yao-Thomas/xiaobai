#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtbanalyze.py —— 把一份设备树按"系统设计"的视角摊开

重点看:
  · 全局: model / chosen(bootargs) / memory / reserved-memory / aliases
  · amba     —— PS 侧外设
  · amba_pl  —— 【PL 侧设计】, 每个 IP 的 compatible / reg / interrupt / clock
"""
import io
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtbdump import parse            # noqa: E402

if not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")


def fmt(v):
    if len(v) == 0:
        return "(空)"
    if len(v) == 4:
        return "0x%08X" % struct.unpack(">I", v)[0]
    if len(v) % 4 == 0 and len(v) <= 24:
        return " ".join("<0x%X>" % struct.unpack(">I", v[i:i + 4])[0]
                        for i in range(0, len(v), 4))
    if all(32 <= c < 127 or c == 0 for c in v):
        p = [x.decode() for x in v.split(b"\x00") if x]
        if p:
            return " ".join(p)
    return v[:20].hex(" ") + ("..." if len(v) > 20 else "")


def walk(path):
    _, _, tree = parse(open(path, "rb").read())
    # 产出 (path, props dict) 与 (path, children)
    stack = []
    nodes = {}       # path -> {prop: raw}
    order = []
    for depth, kind, payload in tree:
        if kind == "node":
            if depth < len(stack):
                stack = stack[:depth]
            stack.append(payload)
            p = "/" + "/".join(stack[1:]) if len(stack) > 1 else "/"
            nodes[p] = {}
            order.append(p)
        elif kind == "prop":
            if stack:
                p = "/" + "/".join(stack[1:]) if len(stack) > 1 else "/"
                nodes[p][payload[0]] = payload[1]
        elif kind == "endnode":
            if depth < len(stack):
                stack = stack[:depth]
    return nodes, order


def show(nodes, order, prefix, indent=2, maxdepth=99, show_props=()):
    base = prefix.rstrip("/")
    n = base.count("/")
    for p in order:
        if not (p == base or p.startswith(base + "/")):
            continue
        d = p.count("/") - n
        if d > maxdepth:
            continue
        # 相对路径
        rel = p[len(base):] or "/"
        print("%s%s" % ("  " * (indent + d - 1), rel.split("/")[-1] or "/"))
        props = nodes.get(p, {})
        keys = show_props or list(props.keys())
        for k in keys:
            if k in props:
                print("%s%-26s = %s" % ("  " * (indent + d), k, fmt(props[k])))


def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    nodes, order = walk(path)

    buf = []
    def P(s=""):
        buf.append(s)
        print(s)

    P("=" * 80)
    P(" %s" % os.path.basename(path))
    P("=" * 80)

    P("\n########## 全局 ##########")
    for k in ("model", "compatible"):
        if k in nodes.get("/", {}):
            P("  %-14s = %s" % (k, fmt(nodes["/"][k])))
    show(nodes, order, "/chosen", 1, 2)
    show(nodes, order, "/memory", 1, 2)
    for p in order:
        if re.match(r"^/reserved-memory", p) or re.match(r"^/aliases", p):
            pass
    show(nodes, order, "/reserved-memory", 1, 2,
         ("reg", "size", "alignment", "no-map", "compatible", "label"))
    P("\n  --- aliases ---")
    for k, v in nodes.get("/aliases", {}).items():
        P("    %-16s = %s" % (k, fmt(v)))

    P("\n########## PS 侧 (/amba) ##########")
    for p in order:
        if p.startswith("/amba/") and p.count("/") == 2:
            pr = nodes.get(p, {})
            cp = fmt(pr.get("compatible", b"")).split()
            P("  %-42s %s" % (p.split("/")[-1], " ".join(cp[:2])))

    P("\n########## PL 侧 (/amba_pl) —— 系统设计的骨架 ##########")
    for p in order:
        if p.startswith("/amba_pl/") and p.count("/") == 2:
            pr = nodes.get(p, {})
            P("")
            P("  === %s ===" % p.split("/")[-1])
            for k in ("compatible", "reg", "interrupts", "interrupt-parent",
                      "clocks", "clock-names", "dmas", "dma-names", "status",
                      "xlnx,vformat", "xlnx,bridge", "xlnx,channels",
                      "reset-gpios", "power-domains", "phy-handle",
                      "xlnx,rable", "port", "iommus"):
                if k in pr:
                    P("      %-22s = %s" % (k, fmt(pr[k])))
            P("      子节点: %s"
              % ", ".join(sorted(set(
                  x[len(p) + 1:].split("/")[0] for x in order
                  if x.startswith(p + "/")))))

    if out:
        open(out, "w", encoding="utf-8").write("\n".join(buf))
        print("\n(已保存 %s)" % out)


main()
