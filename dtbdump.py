#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtbdump.py —— 极简 FDT(设备树) 解析器: 打印节点树 + 关键属性

用法:
    python dtbdump.py <dtb 文件>                 # 只列节点名
    python dtbdump.py <dtb 文件> --full          # 连属性一起
    python dtbdump.py <dtb 文件> --grep lcd      # 只详细展开匹配的节点
"""
import io
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def parse(dtb):
    magic, totalsize, off_struct, off_strings, off_rsvmap, ver, lastver, \
        bootcpu, size_strings, size_struct = struct.unpack(">10I", dtb[:40])
    if magic != 0xD00DFEED:
        raise ValueError("不是 DTB (magic=0x%08X)" % magic)
    strings = dtb[off_strings:off_strings + size_strings]
    struct_blk = dtb[off_struct:off_struct + size_struct]

    def s(off):
        e = strings.find(b"\x00", off)
        return strings[off:e].decode("utf-8", "replace")

    tree = []          # [(depth, kind, name_or_(key,val))]
    pos = 0
    depth = 0
    while pos < len(struct_blk):
        tok = struct.unpack(">I", struct_blk[pos:pos + 4])[0]
        pos += 4
        if tok == FDT_BEGIN_NODE:
            e = struct_blk.find(b"\x00", pos)
            name = struct_blk[pos:e].decode("utf-8", "replace")
            pos = (e + 4) & ~3
            tree.append((depth, "node", name or "/"))
            depth += 1
        elif tok == FDT_END_NODE:
            depth -= 1
            tree.append((depth, "endnode", ""))
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack(">II", struct_blk[pos:pos + 8])
            pos += 8
            val = struct_blk[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            tree.append((depth, "prop", (s(nameoff), val)))
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            break
    return totalsize, ver, tree


def fmt_val(v):
    if len(v) == 0:
        return "(空)"
    if len(v) == 4:
        n = struct.unpack(">I", v)[0]
        return "0x%08X (%d)" % (n, n)
    if len(v) % 4 == 0 and len(v) <= 16:
        return " ".join("<0x%X>" % struct.unpack(">I", v[i:i + 4])[0]
                        for i in range(0, len(v), 4))
    if all(32 <= c < 127 or c == 0 for c in v):
        parts = [p.decode() for p in v.split(b"\x00") if p]
        if parts:
            return " / ".join(parts)
    return v[:24].hex(" ") + ("..." if len(v) > 24 else "")


def main():
    path = sys.argv[1]
    full = "--full" in sys.argv
    grep = None
    if "--grep" in sys.argv:
        grep = sys.argv[sys.argv.index("--grep") + 1].lower()

    data = open(path, "rb").read()
    total, ver, tree = parse(data)
    print("=" * 78)
    print(" %s" % path)
    print(" DTB size=%d  version=%d  节点/属性条目=%d" % (total, ver, len(tree)))
    print("=" * 78)

    path_stack = []
    in_grep = False
    for depth, kind, payload in tree:
        if kind == "node":
            if depth < len(path_stack):
                path_stack = path_stack[:depth]
            path_stack.append(payload)
            if grep:
                in_grep = any(grep in p.lower() for p in path_stack)
            # 默认(无 --full 无 --grep) 列出所有节点名
            show = full or (grep and in_grep) or (not grep and not full)
            if show:
                print("%s%s" % ("  " * depth, payload if payload != "/" else "/"))
        elif kind == "prop":
            key, val = payload
            show = full or (grep and in_grep)
            if show:
                print("%s%-28s = %s" % ("  " * depth, key, fmt_val(val)))
        elif kind == "endnode":
            if depth < len(path_stack):
                path_stack = path_stack[:depth]


if __name__ == "__main__":
    main()
