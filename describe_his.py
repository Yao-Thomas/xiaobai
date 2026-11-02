#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""describe_his.py —— 把"他的系统设计"从设备树里结构化提取出来

输出 D:\\ubuntu_iso\\his_system.txt
"""
import io
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dtbdump import parse, fmt_val

HIS = r"D:\总文件夹\FPGA2026\_ref_boot\fit\fdt-7020.dtb"
OURS = r"D:\总文件夹\FPGA2026\_boot_backup_0926_192947\system.dtb"
OUT = r"D:\ubuntu_iso\his_system.txt"

buf = []


def p(s=""):
    buf.append(s)


def tree_of(path):
    data = open(path, "rb").read()
    total, ver, tree = parse(data)
    nodes = {}          # path -> [(key, val)]
    order = []
    stack = []
    for depth, kind, payload in tree:
        if kind == "node":
            stack = stack[:depth]
            stack.append(payload)
            path_ = "/" + "/".join(x for x in stack if x != "/")
            nodes.setdefault(path_, [])
            order.append(path_)
        elif kind == "prop":
            key, val = payload
            nodes["/" + "/".join(x for x in stack if x != "/")].append((key, val))
    return total, ver, nodes, order


def props(nodes, path, only=None):
    for k, v in nodes.get(path, []):
        if only and k not in only:
            continue
        p("      %-26s = %s" % (k, fmt_val(v)))


def main():
    ht, hv, hn, ho = tree_of(HIS)
    ot, ov, on, oo = tree_of(OURS)

    p("=" * 78)
    p(" 他的系统设计 —— 从 image.ub 内 fdt-7020.dtb 提取")
    p("=" * 78)
    p("DTB %d 字节 version=%d, 节点数 %d" % (ht, hv, len(ho)))
    p("我们的 system.dtb: %d 字节 version=%d, 节点数 %d" % (ot, ov, len(oo)))
    p()

    p("### /chosen 与内存")
    props(hn, "/chosen")
    props(hn, "/memory")
    for n in ho:
        if n.startswith("/reserved-memory"):
            p("    %s" % n)
            props(hn, n)
    p("    /model 等:")
    props(hn, "/", only={"model", "compatible"})
    p()

    p("### /amba_pl —— 这就是他的 PL(Block Design)")
    pl = [n for n in ho if n.startswith("/amba_pl")]
    pl.sort()
    for n in pl:
        ps = hn.get(n, [])
        if not ps:
            p("  %s" % n)
            continue
        comp = ""
        for k, v in ps:
            if k == "compatible":
                comp = fmt_val(v)
        p("  %-42s %s" % (n.replace("/amba_pl/", ""), comp))
    p()
    p("--- 逐个展开 ---")
    for n in pl:
        if n == "/amba_pl":
            continue
        p("  " + n.replace("/amba_pl/", ""))
        props(hn, n)
        p()

    p("### PS 侧外设 (和我们的差异)")
    for n in sorted(set(oo) | set(on)):
        if n.startswith("/amba_pl"):
            continue
        a = sorted(k for k, _ in on.get(n, []))
        b = sorted(k for k, _ in hn.get(n, []))
        if n not in on:
            p("  [只有他有] %s" % n)
        elif n not in hn:
            p("  [只有我们有] %s" % n)
        elif a != b:
            only_h = set(b) - set(a)
            only_o = set(a) - set(b)
            p("  [属性不同] %s   他有:%s 我们有:%s" % (n, sorted(only_h), sorted(only_o)))
    p()

    p("### 节点集合差异")
    only_h = sorted(set(ho) - set(oo))
    only_o = sorted(set(oo) - set(ho))
    p("  只有他有 %d 个:" % len(only_h))
    for n in only_h:
        p("     " + n)
    p("  只有我们有 %d 个:" % len(only_o))
    for n in only_o:
        p("     " + n)
    p()

    p("### 同名节点的属性值差异 (只列前 60 条)")
    cnt = 0
    for n in sorted(set(ho) & set(oo)):
        dh = dict(hn.get(n, []))
        do = dict(on.get(n, []))
        for k in sorted(set(dh) | set(do)):
            if dh.get(k) != do.get(k):
                cnt += 1
                if cnt <= 60:
                    p("  %s :: %s" % (n, k))
                    p("        他 = %s" % (fmt_val(dh[k]) if k in dh else "(无)"))
                    p("        我 = %s" % (fmt_val(do[k]) if k in do else "(无)"))
    p("  ...共 %d 处属性值不同" % cnt)

    open(OUT, "w", encoding="utf8").write("\n".join(buf))
    print("写出 " + OUT)
    print("\n".join(buf[:80]))


main()
