#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fitextract.py —— 从 FIT 镜像(image.ub) 里按名字抽出子镜像

FIT 本身就是一份 DTB, /images/<name>/data 是一个 byte 数组属性。
把 FDT 结构块里的属性值偏移换算成文件绝对偏移, 就能精确切片。
"""
import hashlib
import io
import os
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def parse_with_offsets(dtb, base_off=0):
    """返回 [(depth, kind, payload, file_off)]"""
    magic, totalsize, off_struct, off_strings, off_rsvmap, ver, lastver, \
        bootcpu, size_strings, size_struct = struct.unpack(">10I", dtb[:40])
    assert magic == 0xD00DFEED, "不是 DTB"
    strings = dtb[off_strings:off_strings + size_strings]
    blk = dtb[off_struct:off_struct + size_struct]

    def s(off):
        e = strings.find(b"\x00", off)
        return strings[off:e].decode("utf-8", "replace")

    out = []
    pos = 0
    depth = 0
    while pos < len(blk):
        tok = struct.unpack(">I", blk[pos:pos + 4])[0]
        pos += 4
        if tok == FDT_BEGIN_NODE:
            e = blk.find(b"\x00", pos)
            nm = blk[pos:e].decode("utf-8", "replace")
            pos = (e + 4) & ~3
            out.append((depth, "node", nm or "/", None))
            depth += 1
        elif tok == FDT_END_NODE:
            depth -= 1
            out.append((depth, "endnode", "", None))
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack(">II", blk[pos:pos + 8])
            pos += 8
            val = blk[pos:pos + ln]
            out.append((depth, "prop", (s(nameoff), val),
                        base_off + off_struct + pos))
            pos = (pos + ln + 3) & ~3
        elif tok == FDT_END:
            break
    return out


def main():
    src = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    data = open(src, "rb").read()
    tree = parse_with_offsets(data)

    stack = []
    images = {}
    for depth, kind, payload, foff in tree:
        if kind == "node":
            if depth < len(stack):
                stack = stack[:depth]
            stack.append(payload)
        elif kind == "prop":
            key, val = payload
            # 根的 "/images/<name>/data"
            if key == "data" and "images" in stack:
                images[stack[-1]] = (foff, len(val))
        elif kind == "endnode":
            if depth < len(stack):
                stack = stack[:depth]

    print("FIT 里的子镜像: %s" % ", ".join(sorted(images)))
    print()
    for name, (off, ln) in sorted(images.items()):
        blob = data[off:off + ln]
        md5 = hashlib.md5(blob).hexdigest()
        ext = ".bin"
        if blob[:4] == struct.pack(">I", 0xD00DFEED):
            ext = ".dtb"
        elif blob[:4] == bytes.fromhex("00090ff0"):
            ext = ".bit"
        p = os.path.join(outdir, name + ext)
        open(p, "wb").write(blob)
        print("  %-12s off=0x%08X len=%9d  md5=%s  -> %s"
              % (name, off, ln, md5, os.path.basename(p)))


main()
