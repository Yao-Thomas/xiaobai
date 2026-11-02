#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zimage.py —— 从 ARM zImage 里找出被压缩的内核并解出来, 拿版本号"""
import gzip
import io
import re
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def try_decompress(blob, label):
    out = []
    # gzip
    try:
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        r = d.decompress(blob[:4 << 20], 64 << 20)
        out.append(("gzip", r))
    except Exception:
        pass
    # xz
    try:
        import lzma
        r = lzma.LZMADecompressor().decompress(blob[:8 << 20], 64 << 20)
        out.append(("xz", r))
    except Exception:
        pass
    # lz4
    try:
        import lz4.frame
        r = lz4.frame.decompress(blob[:8 << 20])
        out.append(("lz4", r))
    except Exception:
        pass
    for kind, data in out:
        print("   以 %s 解出 %d 字节" % (kind, len(data)))
        for m in re.finditer(rb"Linux version [\x20-\x7e]{10,160}", data):
            print("     >>> %s" % m.group().decode())


for p in sys.argv[1:]:
    b = open(p, "rb").read()
    print("=" * 76)
    print(" %s (%d 字节)" % (p, len(b)))
    print("=" * 76)
    print("  头 32 字节: %s" % b[:32].hex(" "))
    # ARM zImage: 0x24 处是 magic 0x016F2818
    for off in (0x24, 0x28, 0x2C, 0x30, 0x34, 0x38):
        if off + 4 <= len(b):
            v = int.from_bytes(b[off:off + 4], "little")
            if v in (0x016F2818,):
                print("  ARM zImage magic @0x%X" % off)
    # 找压缩魔数
    for name, magic in (("gzip", b"\x1f\x8b\x08"), ("xz", b"\xfd7zXZ"),
                        ("lz4", b"\x04\x22\x4d\x18"), ("lzma", b"\x5d\x00\x00")):
        i = b.find(magic)
        print("  %-5s 魔数 @ %s" % (name, hex(i) if i >= 0 else "无"))
        if i >= 0:
            try_decompress(b[i:], name)

    # 直接在整份里扫 (有些内核版本串没被压缩掉)
    n = 0
    for m in re.finditer(rb"Linux version [\x20-\x7e]{10,160}", b):
        print("  直接命中: %s" % m.group().decode())
        n += 1
        if n > 3:
            break
    print()
