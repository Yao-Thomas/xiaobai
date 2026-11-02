#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_mem.py —— 逐个地址隔离测试 /dev/mem 能不能读 (SIGBUS 会杀掉进程, 所以一个一个来)"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

ONESHOT = r'''
import mmap, os, struct, sys
base = int(sys.argv[1], 0)
f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
v = struct.unpack("<I", m[0:4])[0]
print("OK 0x%08X = 0x%08X" % (base, v))
'''


def main():
    board.HOST = IP
    open(r"D:\ubuntu_iso\_oneshot.py", "w", encoding="utf8").write(ONESHOT)
    board.put(r"D:\ubuntu_iso\_oneshot.py", "/home/zynq/oneshot.py")
    broot.srun("chown zynq:zynq /home/zynq/oneshot.py", quiet=True)

    print("### 哪些 PL 地址能读 (每个地址单独起一个进程, 崩了不影响下一个)")
    for a in ["0x43CB0000", "0x43CC0000", "0x43C30000", "0x43C50000",
              "0x43C60000", "0x43C70000", "0x41200000", "0x41600000",
              "0x43C00000", "0x43C10000"]:
        out, err = broot.srun(
            "cd /home/zynq && python3 oneshot.py %s 2>&1; echo RC=$?" % a,
            timeout=60, quiet=True)
        line = (out or "").strip().replace("\n", " | ")
        print("  %-12s %s" % (a, line[:110]))
    print()
    print("### /dev/mem 权限 & STRICT_DEVMEM")
    broot.srun("ls -l /dev/mem; zcat /proc/config.gz 2>/dev/null | grep -i STRICT_DEVMEM; "
               "dmesg | grep -i -E 'devmem|strict' | tail -5", timeout=60)


main()
