#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_probe.py —— 在板子上跑 (需要 root): 安全探测两个自研 IP

每个地址 fork 一个子进程再访问 —— 如果该地址没被 bitstream 解码,
ARM 会触发 SIGBUS 直接杀掉进程, fork 出去就只死子进程。
"""
import mmap
import os
import struct
import sys

def rd(base, off):
    # ★ 注意: mmap 的 offset 必须是【页对齐】的, 所以映射整页再在页内偏移读。
    #   直接 mmap(offset=base+off) 会得到 EINVAL (Errno 22)。
    f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
    v = struct.unpack("<I", m[off:off + 4])[0]
    m.close()
    os.close(f)
    return v


TARGETS = [
    ("GPU",   0x43CB0000, 0x00),   # CTRL
    ("SCOPE", 0x43CC0000, 0x34),   # VERSION, 应为 0x53434F50 ("SCOP")
]

for name, base, off in TARGETS:
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        try:
            v = rd(base, off)
            os.write(w, ("OK %08X" % v).encode())
        except Exception as e:
            os.write(w, ("EX %s" % e).encode())
        os.close(w)
        os._exit(0)
    os.close(w)
    msg = os.read(r, 256).decode(errors="replace")
    os.close(r)
    _, st = os.waitpid(pid, 0)
    if st == 0:
        kind, val = msg.split(" ", 1)
        if kind == "OK":
            print("  %-6s 0x%08X [0x%02X] = 0x%08X" % (name, base, off, int(val, 16)))
        else:
            print("  %-6s 0x%08X 异常: %s" % (name, base, val))
    else:
        print("  %-6s 0x%08X  ✗ 被信号杀死 (SIGBUS = 这个地址没解码)"
              % (name, base))

print("DONE")
