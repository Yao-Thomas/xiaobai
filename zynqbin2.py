#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zynqbin2.py —— 解析 Zynq BOOT.BIN, 自动找 boot header 基准, 提取分区

Zynq Boot Header 布局 (UG585 Table 6-1), 相对 header 基准:
   0x00 Width Detection     0xAA995566
   0x04 Image Identification 0x584C4E58 ('XLNX')
   0x08 Encryption Status
   0x0C User Defined
   0x10 Image Offset  <- Image Header Table 的偏移(字节)
   0x14 Image Length
   0x18 Image Execution Address
   0x1C QSPI Configuration Word
   0x20 Boot Device
   ...
   0x30 Checksum

Image Header Table:
   +0x00 Version
   +0x04 Number of Images
   +0x08.. Image Header 偏移 (每个 4 字节)

Image Header:
   +0x00 Next Image Header Offset
   +0x04.. Partition Header 偏移 (每个 4 字节, 到 +0x34)

Partition Header (64 字节):
   +0x00 Encrypted Length (字)
   +0x04 Unencrypted Length (字)
   +0x08 Total Length (字)
   +0x0C Execution Address
   +0x10 Load Address
   +0x14 Data Offset (字节)
   +0x18 Attributes
   +0x1C Section Count
   +0x20 Checksum
   +0x24 Image Header Word 1
   +0x28 Image Header Word 2
   +0x2C Auth Header Offset
"""
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


def u32(off):
    if off + 4 > len(b):
        return 0
    return struct.unpack_from("<I", b, off)[0]


# ---- 1. 找 boot header 基准 ----
base = None
for cand in (0x00, 0x20):
    if u32(cand) == 0xAA995566 and u32(cand + 4) == 0x584C4E58:
        base = cand
        break
if base is None:
    print("❌ 找不到 boot header")
    sys.exit(1)

print("=== Boot Header @ 0x%X ===" % base)
print("  Width Detection = 0x%08X" % u32(base + 0x00))
print("  Identification  = 0x%08X" % u32(base + 0x04))
print("  Encryption      = 0x%08X" % u32(base + 0x08))
print("  User Defined    = 0x%08X" % u32(base + 0x0C))
print("  Image Offset    = 0x%08X  <- 镜像头表" % u32(base + 0x10))
print("  Image Length    = 0x%08X  (%d)" % (u32(base + 0x14), u32(base + 0x14)))
print("  Exec Address    = 0x%08X" % u32(base + 0x18))
print("  QSPI Cfg Word   = 0x%08X" % u32(base + 0x1C))
print("  Boot Device     = 0x%08X" % u32(base + 0x20))
print("  Checksum        = 0x%08X" % u32(base + 0x30))

# ---- 2. Image Header Table ----
iht = base + u32(base + 0x10)
ver = u32(iht)
nimg = u32(iht + 4)
print("\n=== Image Header Table @ 0x%X ===" % iht)
print("  Version=%d   Images=%d" % (ver, nimg))
if nimg == 0 or nimg > 8:
    print("  ⚠ 镜像数不合理, 结构可能不对")
    sys.exit(1)
ihs = [base + u32(iht + 8 + i * 4) for i in range(nimg)]
for i, o in enumerate(ihs):
    print("  Image Header[%d] @ 0x%X" % (i, o))

# ---- 3. 遍历分区 ----
print()
parts = []
for ii, ih in enumerate(ihs):
    nm = b[ih + 0x38:ih + 0x38 + 16].split(b"\x00")[0].decode("ascii", "replace")
    print("=== Image Header %d @ 0x%X  name=%r  id=0x%08X ==="
          % (ii, ih, nm, u32(ih + 0x50)))
    for k in range((0x38 - 0x04) // 4):
        ph = u32(ih + 0x04 + k * 4)
        if ph == 0:
            continue
        ph = base + ph
        enc, unenc, total = u32(ph), u32(ph + 4), u32(ph + 8)
        execa, load = u32(ph + 0x0C), u32(ph + 0x10)
        off = u32(ph + 0x14)
        attr, sect, csum = u32(ph + 0x18), u32(ph + 0x1C), u32(ph + 0x20)
        ih1, ih2 = u32(ph + 0x24), u32(ph + 0x28)
        magic = b[off:off + 4]
        kind = "?"
        if magic == b"\x7fELF":
            kind = "ELF"
        elif magic[:3] == b"\xbb\x00\x00" or magic[:3] == b"\x00\x00\x00":
            kind = "bitstream?"
        elif magic[:2] == b"\x1f\x8b":
            kind = "gzip"
        print("  分区[%d.%d] 头@0x%X  数据@0x%X  长度=%d 字=%d 字节  %s"
              % (ii, k, ph, off, total, total * 4, kind))
        print("       执行=0x%08X 加载=0x%08X 属性=0x%08X 段=%d 校验=0x%08X"
              % (execa, load, attr, sect, csum))
        print("       数据头: %s" % magic.hex(" "))
        parts.append(dict(img=ii, idx=k, ph=ph, off=off, total=total,
                          unenc=unenc, execa=execa, load=load, attr=attr,
                          csum=csum, kind=kind))
    print()

print("=" * 60)
print("共 %d 个分区" % len(parts))
for p in parts:
    print("  0x%08X .. 0x%08X  (%9d 字节)  %s"
          % (p["off"], p["off"] + p["total"] * 4, p["total"] * 4, p["kind"]))
