#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gpu_probe.py —— 探测 0x43CB0000 上到底有没有我们的 GPU

单独跑一个进程, 因为如果 PL 没配置好, 读未解码地址会触发 SIGBUS
直接把进程打死(返回 -7)。这本身就是最明确的"没加载"信号。
"""
import mmap
import os
import struct
import sys

BASE = 0x43CB0000
PAGE = 0x1000

NAMES = [
    (0x00, "CTRL"), (0x04, "OP"), (0x08, "BASE"), (0x0C, "STRIDE"),
    (0x10, "XY0"), (0x14, "XY1"), (0x18, "COLOR"), (0x1C, "PIXCNT"),
    (0x20, "STATUS"),
]

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
try:
    m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
    regs = {}
    for off, name in NAMES:
        regs[name] = struct.unpack("<I", m[off:off + 4])[0]
    m.close()
except Exception as e:
    print("探测失败: %s" % e)
    os.close(fd)
    sys.exit(1)
finally:
    try:
        os.close(fd)
    except Exception:
        pass

print("✅ 0x%08X 已解码, 寄存器可读:" % BASE)
for off, name in NAMES:
    print("   +0x%02X %-8s = 0x%08X" % (off, name, regs[name]))

if regs["STRIDE"] in (0, 0xFFFFFFFF) and regs["STATUS"] in (0, 0xFFFFFFFF):
    print("⚠ 读出全 1/全 0, 像是总线 DECERR, 不一定是我们的 IP")
    sys.exit(2)
sys.exit(0)
