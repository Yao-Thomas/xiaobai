#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bootbin.py —— 解析 Xilinx Zynq BOOT.BIN 的启动头 + 分区表

Zynq-7000 Boot Image (UG585):
  BootROM header
    0x000 中断向量表 (8 x u32)
    0x020 Image Identification (0x20 字节)
    0x040 加密密钥 (0x100, 仅加密镜像)
    ...   Image Header Table
            +0x00 Version
            +0x04 Image Header Table 偏移
            +0x08 镜像个数
            +0x0C Image Header 偏移
            +0x10 认证证书偏移
    ...   Image Header (每个镜像一个, 0x40 字节)
            +0x00 下一个镜像头的偏移
            +0x04 分区头表偏移
            +0x08 分区个数
            ...
          Partition Header (每个分区 0x40 字节)
            +0x00 未加密数据字长 (字节)
            +0x04 已加密数据字长
            +0x08 已加载数据字长
            +0x0C 执行地址
            +0x10 数据偏移 (从 BOOT.BIN 起始算, 单位字节)
            +0x14 属性 (bit4=1 -> 这是一个比特流分区!)
            +0x18 分区数据段个数
            +0x1C 校验和
"""
import io
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

P = r"D:\总文件夹\FPGA2026\_ref_boot\BOOT.BIN"
b = open(P, "rb").read()
print("=" * 78)
print(" BOOT.BIN  %d 字节" % len(b))
print("=" * 78)

# ---- 中断向量表 ----
vec = struct.unpack("<8I", b[0:32])
print(" 中断向量表: %s" % " ".join("%08X" % v for v in vec))

# ---- Image Identification ----
ident = b[0x20:0x40].split(b"\x00")[0].decode("latin-1", "replace")
print(" Image Identification: %r" % ident)

# ---- 找 Image Header Table ----
# 未加密镜像: 通常紧跟在 id 之后。扫描 0x40..0x400 找看起来像 IHT 的位置
def looks_like_iht(off):
    if off + 0x14 > len(b):
        return False
    ver = struct.unpack("<I", b[off:off + 4])[0]
    ihc = struct.unpack("<I", b[off + 0x0C:off + 0x10])[0]
    return ver in (0x01010000, 0x00010000, 1) and 0 < ihc < 0x4000

iht_off = None
for off in range(0x40, 0x400, 4):
    if looks_like_iht(off):
        iht_off = off
        break
print(" Image Header Table 偏移: %s" % (hex(iht_off) if iht_off else "(没找到)"))

if iht_off is not None:
    ver, ihtoff2, nimg, ihoff = struct.unpack("<4I", b[iht_off:iht_off + 16])
    print("   version=0x%08X  iht_offset=0x%X  num_images=%d  ih_offset=0x%X"
          % (ver, ihtoff2, nimg, ihoff))

    for im in range(nimg):
        ih = ihoff + im * 0x40
        nxt, phoff, npart = struct.unpack("<3I", b[ih:ih + 12])
        print("")
        print(" ---- 镜像 %d : 分区头表 @0x%X, 分区数 %d ----" % (im, phoff, npart))
        for pk in range(npart):
            ph = phoff + pk * 0x40
            (ulen, elen, llen, execaddr, dataoff,
             attrs) = struct.unpack("<6I", b[ph:ph + 24])
            nseg = struct.unpack("<I", b[ph + 0x18:ph + 0x1C])[0]
            csum = struct.unpack("<I", b[ph + 0x1C:ph + 0x20])[0]
            is_bit = (attrs >> 4) & 1
            is_elf = (attrs >> 5) & 1
            kind = []
            if is_bit:
                kind.append("★比特流")
            if is_elf:
                kind.append("ELF")
            if attrs & 0xF:
                kind.append("attrs=0x%X" % attrs)
            head = ""
            if 0 < dataoff < len(b) - 16:
                head = b[dataoff:dataoff + 16].hex(" ")
            print("   分区%d: 未加密%7d 已加密%7d 加载%7d  执行地址 0x%08X  数据@0x%06X  %s"
                  % (pk, ulen, elen, llen, execaddr, dataoff,
                     " ".join(kind) or "(普通数据)"))
            print("            段数=%d 校验和=0x%08X  头16字节: %s"
                  % (nseg, csum, head))

# ---- 扫比特流同步字 ----
print("")
print("=" * 78)
print(" 在 BOOT.BIN 里搜 7 系列比特流同步字 AA 99 55 66")
print("=" * 78)
sync = bytes.fromhex("AA995566")
idx = []
i = 0
while True:
    i = b.find(sync, i)
    if i < 0:
        break
    idx.append(i)
    i += 1
print(" 命中 %d 处: %s" % (len(idx), [hex(x) for x in idx[:10]]))

# ---- 扫其它已知头 ----
for name, pat in ((".bit 文本头", b"design filename"),
                  ("Zynq fsbl", b"FSBL"),
                  ("u-boot", b"U-Boot"),
                  ("devicetree", b"devicetree")):
    j = b.find(pat)
    print(" %-14s @%s" % (name, hex(j) if j >= 0 else "无"))
