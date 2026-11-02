#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看匿名大块里最长能拿到多长的物理连续段 (用 pagemap 拿 PFN)"""
import ctypes
import mmap
import os
import struct
import sys

PAGE = 4096
POOL = int(sys.argv[1]) if len(sys.argv) > 1 else 4 << 20


def pfn_of(fd, va):
    os.lseek(fd, (va // PAGE) * 8, os.SEEK_SET)
    d = os.read(fd, 8)
    e = struct.unpack("<Q", d)[0]
    return (e >> 63) & 1, e & ((1 << 55) - 1)


def longest_run(npfn):
    """npfn: list of pfn (0 表示无效)"""
    best = (0, 0, 0)
    i = 0
    n = len(npfn)
    while i < n:
        if not npfn[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and npfn[j + 1] == npfn[j] + 1:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, i, j)
        i = j + 1
    return best


print("meminfo:")
for line in open("/proc/meminfo"):
    if "Huge" in line or "MemFree" in line or "MemAvailable" in line:
        print("   ", line.strip(), flush=True)

for p in ("/sys/kernel/mm/transparent_hugepage/enabled",
          "/sys/kernel/mm/transparent_hugepage/defrag"):
    try:
        print(p, "=", open(p).read().strip(), flush=True)
    except Exception as e:
        print(p, "!!", e, flush=True)

npages = POOL // PAGE
buf = mmap.mmap(-1, POOL, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
# 按页触碰, 一次一页 (跟真实分配顺序一致)
for i in range(npages):
    buf[i * PAGE] = 1
buf.write(b"\x00" * (PAGE * 4))     # 保证不是空洞
va = ctypes.addressof(ctypes.c_char.from_buffer(buf))
print("va=0x%x pages=%d" % (va, npages), flush=True)

fd = os.open("/proc/self/pagemap", os.O_RDONLY)
try:
    pfns = []
    for i in range(npages):
        pr, p = pfn_of(fd, va + i * PAGE)
        pfns.append(p if pr else 0)
finally:
    os.close(fd)

print("前 24 个 pfn:", [hex(p) for p in pfns[:24]], flush=True)
print("起始物理 0x%x" % (pfns[0] * PAGE), flush=True)

run, i, j = longest_run(pfns)
print(">>> 最长连续段 = %d 页 (%d 字节) 位于第 %d..%d 页" %
      (run, run * PAGE, i, j), flush=True)

# 统计: 有多少个 >= 8 页的段
segs = []
k = 0
while k < npages:
    if not pfns[k]:
        k += 1
        continue
    m = k
    while m + 1 < npages and pfns[m + 1] == pfns[m] + 1:
        m += 1
    segs.append(m - k + 1)
    k = m + 1
segs.sort(reverse=True)
print("所有连续段长度 (降序前 20):", segs[:20], flush=True)
print("总段数 =", len(segs), flush=True)
