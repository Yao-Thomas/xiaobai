# -*- coding: utf-8 -*-
"""dumpboot.py —— 原始 dump BOOT.BIN 开头, 并找关键特征字"""
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\总文件夹\FPGA2026\系统备份\引导文件\BOOT.BIN"
b = open(P, "rb").read()
print("文件 %s  %d 字节\n" % (P, len(b)))

print("=== 前 0x120 字节 ===")
for o in range(0, 0x120, 16):
    hexs = " ".join("%02x" % c for c in b[o:o + 16])
    word = struct.unpack_from("<I", b, o)[0] if o + 4 <= len(b) else 0
    print("  %04X: %-47s  %08X" % (o, hexs, word))

print("\n=== 找关键特征 ===")


def find(pat, limit=8):
    hits = []
    start = 0
    while len(hits) < limit:
        i = b.find(pat, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    return hits


for lbl, pat in [
    ("宽度检测 AA995566", b"\x66\x55\x99\xaa"),
    ("宽度检测 (交换) BB000000", b"\xbb\x00\x00\x00"),
    ("宽度检测 (未交换) 000000BB", b"\x00\x00\x00\xbb"),
    ("XLNX 标识", b"\x58\x4e\x4c\x58"),
    ("ELF 头", b"\x7fELF"),
    ("bitstream 同步 AA995566(后)", b"\x66\x55\x99\xaa\x20\x00\x00\x00"),
]:
    h = find(pat)
    print("  %-28s -> %s" % (lbl, ["0x%X" % x for x in h[:6]] or "没找到"))
