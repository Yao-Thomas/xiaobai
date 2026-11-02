#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_pl_audio.py —— 读 clk_wiz / i2s / formatter 的寄存器, 把音频链路现状摸清"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

PY = r'''
import mmap, os, struct, sys

def rd32(base, off):
    f = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
    v = struct.unpack("<I", m[off:off+4])[0]
    m.close(); os.close(f)
    return v

print("=== clk_wiz @0x43C30000 (0x200~0x260) ===")
for off in range(0x200, 0x264, 4):
    try:
        v = rd32(0x43C30000, off)
        print("  0x%03X = 0x%08X  (%d)" % (off, v, v))
    except Exception as e:
        print("  0x%03X 读失败 %s" % (off, e))
        break

print()
print("=== AXI I2S 发送器 @0x43C70000 ===")
for off in (0x00, 0x04, 0x08, 0x20, 0x30, 0x34, 0x38, 0x3C):
    try:
        print("  0x%02X = 0x%08X" % (off, rd32(0x43C70000, off)))
    except Exception as e:
        print("  0x%02X 读失败 %s" % (off, e))

print()
print("=== AXI I2S 接收器 @0x43C60000 ===")
for off in (0x00, 0x04, 0x08, 0x20, 0x30, 0x34):
    try:
        print("  0x%02X = 0x%08X" % (off, rd32(0x43C60000, off)))
    except Exception as e:
        print("  0x%02X 读失败 %s" % (off, e))

print()
print("=== audio formatter @0x43C50000 (MM2S 0x100 起) ===")
for off in (0x00, 0x04, 0x10, 0x14, 0x18, 0x1C, 0x100, 0x104, 0x110, 0x114,
            0x118, 0x11C, 0x120, 0x124, 0x128, 0x12C, 0x144):
    try:
        print("  0x%03X = 0x%08X" % (off, rd32(0x43C50000, off)))
    except Exception as e:
        print("  0x%03X 读失败 %s" % (off, e))
'''


def main():
    board.HOST = IP
    open(r"D:\ubuntu_iso\_pl_audio_probe.py", "w", encoding="utf8").write(PY)
    board.put(r"D:\ubuntu_iso\_pl_audio_probe.py", "/home/zynq/pl_audio_probe.py")
    broot.srun("chown zynq:zynq /home/zynq/pl_audio_probe.py", quiet=True)
    broot.srun("cd /home/zynq && python3 pl_audio_probe.py", timeout=300)


main()
