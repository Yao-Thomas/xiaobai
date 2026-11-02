#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peek_boot.py —— 看别人的 BOOT.BIN / boot.scr / image.ub 是什么板子什么系统"""
import io
import os
import re
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

D = r"D:\总文件夹\FPGA2026\_ref_boot"


def read(p):
    return open(os.path.join(D, p), "rb").read()


print("=" * 78)
print(" boot.scr  (u-boot script: 64 字节头 + 明文脚本)")
print("=" * 78)
b = read("boot.scr")
print("  大小 %d 字节" % len(b))
print("  头 8 字节: %s" % b[:8].hex(" "))
body = b[64:]
txt = body.decode("utf-8", "replace")
print("  --- 脚本正文 ---")
for line in txt.splitlines():
    print("    " + line.rstrip())

print()
print("=" * 78)
print(" BOOT.BIN")
print("=" * 78)
b = read("BOOT.BIN")
print("  大小 %d 字节" % len(b))
print("  头 16 字节: %s" % b[:16].hex(" "))
# Xilinx BootROM header (Zynq)
if b[:4] == b"XLNX" or b[0x24:0x28] == b"XLNX":
    print("  -> Xilinx Zynq BootROM header (XLNX)")
    try:
        # image identification string at offset 0x20, len 0x20
        ident = b[0x20:0x40]
        print("  image identification: %r" % ident.rstrip(b"\x00"))
    except Exception:
        pass
# 找内嵌的字符串
for pat in (b"FSBL", b"zynq", b"BOOT.bin", b"system.bit", b"u-boot"):
    i = b.find(pat)
    if i >= 0:
        print("  含 %-12s @0x%X" % (pat.decode(), i))
print("  --- 前若干可打印字符串 ---")
seen = 0
for m in re.finditer(rb"[\x20-\x7e]{8,}", b[:200000]):
    s = m.group().decode()
    print("    @0x%06X %s" % (m.start(), s[:100]))
    seen += 1
    if seen >= 25:
        break

print()
print("=" * 78)
print(" image.ub  (FIT image: kernel + dtb + rootfs?)")
print("=" * 78)
b = read("image.ub")
print("  大小 %d 字节" % len(b))
print("  头 16 字节: %s" % b[:16].hex(" "))
if b[:4] == struct.pack(">I", 0xD00DFEED):
    print("  -> 直接是 DTB (device tree blob)")
tot = struct.unpack(">I", b[4:8])[0]
print("  FIT total size = %d (文件 %d)" % (tot, len(b)))
print("  --- 前 3000 字节里的可打印串 ---")
n = 0
for m in re.finditer(rb"[\x20-\x7e]{6,}", b[:6000]):
    s = m.group().decode()
    print("    @0x%05X %s" % (m.start(), s[:110]))
    n += 1
    if n >= 60:
        break

print()
print("  --- 搜 DTB 魔数 (找内嵌设备树) ---")
idx = []
i = 0
while True:
    i = b.find(struct.pack(">I", 0xD00DFEED), i)
    if i < 0:
        break
    idx.append(i)
    i += 1
print("  找到 %d 处: %s" % (len(idx), [hex(x) for x in idx[:10]]))
for off in idx[:3]:
    tot2 = struct.unpack(">I", b[off + 4:off + 8])[0]
    seg = b[off:off + tot2]
    comp = re.findall(rb"[\x20-\x7e]{5,}", seg[:200000])
    interesting = [c.decode() for c in comp
                   if any(k in c for k in (b"model", b"compatible", b"xlnx",
                                           b"zynq", b"atk", b"ALIENTEK",
                                           b"Navigator", b"7000", b"7020"))]
    print("    DTB @0x%X size=%d  关键串: %s" % (off, tot2, interesting[:12]))
