#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pl_read.py —— 读 PL 里任意地址的寄存器

用法: python3 pl_read.py 0x43C20000 [个数]
地址没解码会 SIGBUS 直接死掉, 这是正常的探测信号。
"""
import mmap
import os
import struct
import sys

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

addr = int(sys.argv[1], 16)
n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
size = 0x1000

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
try:
    m = mmap.mmap(fd, size, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=addr & ~0xFFF)
    off = addr & 0xFFF
    for i in range(n):
        v = struct.unpack("<I", m[off + i * 4: off + i * 4 + 4])[0]
        print("  0x%08X = 0x%08X  (%d)" % (addr + i * 4, v, v))
    m.close()
finally:
    os.close(fd)
