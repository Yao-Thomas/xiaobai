#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zynqbin.py —— 解析 Zynq BOOT.BIN (Boot Image) 的分区表

格式参考 UG585 第 6 章:
  Boot Header -> Image Header Table -> Image Header -> Partition Header -> 数据
长度字段单位是【32 位字】, 偏移字段单位是【字节】。
"""
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def u32(b, off):
    return struct.unpack_from("<I", b, off)[0]


def name(b, off, n=16):
    raw = b[off:off + n]
    return raw.split(b"\x00")[0].decode("ascii", "replace")


def parse(path):
    b = open(path, "rb").read()
    print("文件: %s  (%d 字节)" % (path, len(b)))
    print()

    wd = u32(b, 0x00)
    ident = u32(b, 0x04)
    print("=== Boot Header ===")
    print("  宽度检测字   = 0x%08X  (应为 0xAA995566)" % wd)
    print("  镜像标识     = 0x%08X  (应为 0x584C4E58 'XLNX')" % ident)
    print("  加密状态     = 0x%08X" % u32(b, 0x08))
    print("  用户定义     = 0x%08X" % u32(b, 0x0C))
    print("  源偏移       = 0x%08X  <- 镜像头表位置" % u32(b, 0x10))
    print("  镜像长度     = 0x%08X" % u32(b, 0x14))
    print("  镜像执行地址 = 0x%08X" % u32(b, 0x18))
    print("  QSPI 配置字  = 0x%08X" % u32(b, 0x1C))
    print("  启动设备     = 0x%08X" % u32(b, 0x20))
    print("  校验和       = 0x%08X" % u32(b, 0x30))
    print()

    iht = u32(b, 0x10)
    ver = u32(b, iht + 0x00)
    nimg = u32(b, iht + 0x04)
    print("=== Image Header Table @ 0x%X ===" % iht)
    print("  版本 = 0x%08X   镜像数 = %d" % (ver, nimg))
    ih_offsets = []
    for i in range(nimg):
        o = u32(b, iht + 0x08 + i * 4)
        ih_offsets.append(o)
        print("  镜像头[%d] @ 0x%08X" % (i, o))
    print()

    total_parts = 0
    for idx, ih in enumerate(ih_offsets):
        nxt = u32(b, ih + 0x00)
        print("=== Image Header %d @ 0x%X (next=0x%X) ===" % (idx, ih, nxt))
        print("  镜像名 = %r" % name(b, ih + 0x38))
        print("  镜像ID = 0x%08X" % u32(b, ih + 0x50))
        # 分区头偏移从 0x04 开始, 直到 0x38
        for k in range((0x38 - 0x04) // 4):
            ph = u32(b, ih + 0x04 + k * 4)
            if ph == 0:
                continue
            _dump_part(b, ph, idx, k)
            total_parts += 1
        print()
    print("共 %d 个镜像, %d 个分区" % (len(ih_offsets), total_parts))


def _dump_part(b, ph, img, k):
    enc = u32(b, ph + 0x00)
    unenc = u32(b, ph + 0x04)
    total = u32(b, ph + 0x08)
    execa = u32(b, ph + 0x0C)
    load = u32(b, ph + 0x10)
    off = u32(b, ph + 0x14)
    attr = u32(b, ph + 0x18)
    sect = u32(b, ph + 0x1C)
    csum = u32(b, ph + 0x20)
    ih1 = u32(b, ph + 0x24)
    ih2 = u32(b, ph + 0x28)
    print("  --- 分区[%d.%d] 头 @ 0x%X ---" % (img, k, ph))
    print("     加密长度 = %-8d 字  (未加密长度 %d 字 = %d 字节)"
          % (enc, unenc, unenc * 4))
    print("     总长度   = %-8d 字 = %d 字节" % (total, total * 4))
    print("     执行地址 = 0x%08X   加载地址 = 0x%08X" % (execa, load))
    print("     数据偏移 = 0x%08X  (文件里 %d..%d)"
          % (off, off, off + total * 4))
    print("     属性     = 0x%08X   段数 = %d   校验和 = 0x%08X" % (attr, sect, csum))
    print("     镜像ID   = 0x%08X 0x%08X" % (ih1, ih2))
    # 数据头部特征
    head = b[off:off + 16]
    print("     数据头   = %s | %r" % (head.hex(" "), head[:4]))
    if b[off:off + 4] == b"\x7fELF":
        print("     ★ 这是 ELF 文件")
    elif b[off:off + 4] == b"\x00\x00\x00\xbb" or b[off:off + 4] == b"\xbb\x00\x00\x00":
        print("     ★ 这是 bitstream (同步字)")
    elif b[off:off + 2] == b"\x1f\x8b":
        print("     ★ 这是 gzip 压缩数据")


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else \
        r"D:\总文件夹\FPGA2026\系统备份\引导文件\BOOT.BIN"
    parse(p)
