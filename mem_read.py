#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mem_read.py <hexbase> <hexoff> [count] —— 一个进程只碰一个 /dev/mem 页"""
import mmap
import os
import struct
import sys

base = int(sys.argv[1], 16)
off = int(sys.argv[2], 16)
n = int(sys.argv[3]) if len(sys.argv) > 3 else 1
mode = sys.argv[4] if len(sys.argv) > 4 else "rw"
prot = mmap.PROT_READ | (mmap.PROT_WRITE if mode == "rw" else 0)
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
try:
    m = mmap.mmap(fd, 4096, mmap.MAP_SHARED, prot, offset=base)
    for i in range(n):
        v = struct.unpack("<I", m[off + 4 * i:off + 4 * i + 4])[0]
        print("0x%08X = 0x%08X (%d)" % (base + off + 4 * i, v, v))
    m.close()
finally:
    os.close(fd)
