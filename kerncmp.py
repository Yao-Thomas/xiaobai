#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kerncmp.py —— 逐字节比对我们和他在 image.ub 里的内核

两者 config 的 md5 已经一致, 裸内核大小也一致 (12769856)。
如果差异只集中在 UTS 版本串那一小段, 就说明是同一源码+同一 config 的两次编译,
那么 CONFIG_MODVERSIONS 的符号 CRC 表也应当一致 -> 我们的 .ko 能装进他的内核。
"""
import gzip
import hashlib
import io
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def bare(path):
    d = open(path, "rb").read()
    m = d.find(b"\x1f\x8b\x08")
    o = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = o.decompress(d[m:]) + o.flush()
    return out


A = bare(r"D:\总文件夹\FPGA2026\_ref_boot\fit\kernel-1.bin")   # 他的
B = bare(r"D:\总文件夹\FPGA2026\_boot_backup_0926_192947\zImage")  # 我们的

print("他的裸内核 %d  md5=%s" % (len(A), hashlib.md5(A).hexdigest()))
print("我们的裸内核 %d md5=%s" % (len(B), hashlib.md5(B).hexdigest()))
print("长度相同:", len(A) == len(B))

if len(A) == len(B):
    diff = [i for i in range(len(A)) if A[i] != B[i]]
    print("不同字节数: %d / %d  (%.4f%%)" % (len(diff), len(A), 100.0 * len(diff) / len(A)))
    # 归并成区间
    runs = []
    for i in diff:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    print("差异区间数: %d" % len(runs))
    for a, b in runs[:40]:
        ctx = A[max(0, a - 24):b + 25]
        printable = "".join(chr(c) if 32 <= c < 127 else "." for c in ctx)
        print("  @0x%08X len=%d  A=%r" % (a, b - a + 1, printable))
        print("  %-22s B=%r" % ("", "".join(
            chr(c) if 32 <= c < 127 else "." for c in B[max(0, a - 24):b + 25])))
    if len(runs) > 40:
        print("  ... 还有 %d 段" % (len(runs) - 40))

    # 版本串定位
    for tag, K in (("他的", A), ("我们的", B)):
        i = K.find(b"5.4.0-xilinx-v2020.2")
        print("%s UTS 串 @0x%X: %r" % (tag, i, K[i - 8:i + 120]))
