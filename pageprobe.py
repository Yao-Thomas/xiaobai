#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 root 下 /proc/self/pagemap 是否给出真实 PFN"""
import ctypes
import mmap
import os
import struct
import sys

print("uid =", os.getuid(), flush=True)
print("pagemap exists:", os.path.exists("/proc/self/pagemap"), flush=True)
try:
    st = os.stat("/proc/self/pagemap")
    print("stat size =", st.st_size, flush=True)
except Exception as e:
    print("stat err", e, flush=True)

n = 64 * 1024
buf = mmap.mmap(-1, n, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
buf.write(b"\xaa" * n)
va = ctypes.addressof(ctypes.c_char.from_buffer(buf))
print("va = 0x%x" % va, flush=True)

fd = os.open("/proc/self/pagemap", os.O_RDONLY)
try:
    pfns = []
    for off in range(0, n, 4096):
        os.lseek(fd, ((va + off) // 4096) * 8, os.SEEK_SET)
        d = os.read(fd, 8)
        if len(d) < 8:
            print("short read at", off, repr(d), flush=True)
            break
        e = struct.unpack("<Q", d)[0]
        pfns.append(((e >> 63) & 1, e & ((1 << 55) - 1)))
finally:
    os.close(fd)

print("present =", [p[0] for p in pfns], flush=True)
print("pfn     =", [hex(p[1]) for p in pfns], flush=True)
ok = all(p[0] == 1 for p in pfns) and pfns[0][1] != 0 and \
    all(pfns[i + 1][1] == pfns[i][1] + 1 for i in range(len(pfns) - 1))
print(">>> PFN 可用且物理连续 =", ok, flush=True)
if pfns and pfns[0][1]:
    print(">>> 起始物理地址 = 0x%x" % (pfns[0][1] * 4096), flush=True)
