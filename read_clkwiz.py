#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read_clkwiz.py —— 逐个地址(单进程)读 clk_wiz 寄存器, 用来反推 MCLK"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

ONESHOT = r'''
import mmap, os, struct, sys
base = int(sys.argv[1], 0); off = int(sys.argv[2], 0)
f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
v = struct.unpack("<I", m[off:off+4])[0]
print("0x%03X=0x%08X" % (off, v))
'''


def main():
    board.HOST = IP
    open(r"D:\ubuntu_iso\_oneshot2.py", "w", encoding="utf8").write(ONESHOT)
    board.put(r"D:\ubuntu_iso\_oneshot2.py", "/home/zynq/oneshot2.py")
    broot.srun("chown zynq:zynq /home/zynq/oneshot2.py", quiet=True)

    print("### clk_wiz @0x43C30000 寄存器扫描 (PG065: 0x200+4n = 第 n 路输出配置)")
    vals = {}
    for off in range(0x200, 0x264, 4):
        out, err = broot.srun(
            "cd /home/zynq && python3 oneshot2.py 0x43C30000 0x%X 2>&1" % off,
            timeout=45, quiet=True)
        s = (out or "").strip()
        if "=" in s:
            vals[off] = int(s.split("=")[1], 16)
            print("   %s" % s)
        else:
            print("   0x%03X  <读不到: %s>" % (off, (err or "").strip()[:40]))

    print()
    print("### 解读")
    for off in range(0x200, 0x220, 4):
        v = vals.get(off)
        if v is None:
            continue
        div = v & 0xFF
        print("   0x%03X = 0x%08X  低8位(分频?)=%d  [10:8]=%d  bit31=%d"
              % (off, v, div, (v >> 8) & 7, (v >> 31) & 1))


main()
