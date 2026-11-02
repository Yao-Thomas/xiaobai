#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频前置探针: MCLK 源 / clk_wiz 状态 / pagemap 可用性 / ES8388"""
import os
import struct
import sys
import mmap
import fcntl

I2C_SLAVE = 0x0703


def read_prop(p):
    try:
        with open(p, "rb") as f:
            return f.read()
    except Exception as e:
        return None


print("### 1. misc_clk_0 / clk_wiz DT")
for base in ("/proc/device-tree/amba_pl/misc_clk_0",
             "/proc/device-tree/amba_pl/misc_clk_1",
             "/proc/device-tree/amba_pl/misc_clk_2",
             "/proc/device-tree/amba_pl/clk_wiz@43c30000"):
    if not os.path.isdir(base):
        print("  (缺) %s" % base)
        continue
    print("  %s:" % base)
    for n in sorted(os.listdir(base)):
        p = os.path.join(base, n)
        if not os.path.isfile(p):
            continue
        v = read_prop(p)
        if v is None:
            continue
        if n in ("compatible", "clock-output-names", "clock-names"):
            print("    %-22s = %r" % (n, [x for x in v.split(b"\0") if x]))
        elif len(v) == 4:
            print("    %-22s = %d" % (n, struct.unpack(">I", v)[0]))
        else:
            print("    %-22s = %s" % (n, v.hex()))

print()
print("### 2. /proc/self/pagemap 可用性")
try:
    sz = os.path.getsize("/proc/self/pagemap")
    print("  pagemap size = %d (页数 %d)" % (sz, sz // 8))
    # 分配 64KB 并触碰
    n = 64 * 1024
    buf = mmap.mmap(-1, n, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
    buf.write(b"\xaa" * n)
    # 用 ctypes 拿虚拟地址
    import ctypes
    va = ctypes.addressof(ctypes.c_char.from_buffer(buf))
    print("  va = 0x%x" % va)
    fd = os.open("/proc/self/pagemap", os.O_RDONLY)
    try:
        pfn = []
        for off in range(0, n, 4096):
            os.lseek(fd, ((va + off) // 4096) * 8, os.SEEK_SET)
            d = os.read(fd, 8)
            e = struct.unpack("<Q", d)[0]
            present = (e >> 63) & 1
            p = e & ((1 << 55) - 1)
            pfn.append((present, p))
    finally:
        os.close(fd)
    print("  present = %s" % [x[0] for x in pfn])
    print("  pfn     = %s" % [hex(x[1]) for x in pfn])
    ok = all(x[0] == 1 for x in pfn) and all(
        pfn[i + 1][1] == pfn[i][1] + 1 for i in range(len(pfn) - 1))
    print("  >>> 物理连续且 present = %s" % ok)
    if pfn[0][0]:
        print("  >>> 起始物理地址 = 0x%x" % (pfn[0][1] * 4096))
except Exception as e:
    print("  !! %s: %s" % (type(e).__name__, e))

print()
print("### 3. clk_wiz@0x43C30000 寄存器 (MMCM 状态)")
try:
    PAGE = 4096
    base = 0x43C30000
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        for off in (0x000, 0x004, 0x008, 0x00C, 0x200, 0x204, 0x208,
                    0x20C, 0x210, 0x214, 0x218, 0x21C, 0x220, 0x224,
                    0x228, 0x22C, 0x230, 0x234, 0x238, 0x23C, 0x240,
                    0x244, 0x248, 0x24C, 0x250, 0x254, 0x258, 0x25C, 0x260):
            v = struct.unpack("<I", m[off:off + 4])[0]
            print("  0x%03X = 0x%08X (%d)" % (off, v, v))
        m.close()
    finally:
        os.close(fd)
except Exception as e:
    print("  !! %s: %s" % (type(e).__name__, e))

print()
print("### 4. ES8388 @ /dev/i2c-1 addr 0x10")
try:
    fd = os.open("/dev/i2c-1", os.O_RDWR)
    try:
        fcntl.ioctl(fd, I2C_SLAVE, 0x10)
        for reg in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11,
                    0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A,
                    0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23,
                    0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C,
                    0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35,
                    0x36, 0x37, 0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E,
                    0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47,
                    0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x50,
                    0x51, 0x52):
            try:
                os.write(fd, bytes([reg]))
                v = os.read(fd, 1)
                print("  0x%02X = 0x%02X" % (reg, v[0]))
            except Exception as e:
                print("  0x%02X = !! %s" % (reg, e))
    finally:
        os.close(fd)
except Exception as e:
    print("  !! %s: %s" % (type(e).__name__, e))

print()
print("### 5. formatter / i2s 当前寄存器快照")
for name, base, offs in (
        ("formatter", 0x43C50000,
         [0x000, 0x004, 0x010, 0x014, 0x018, 0x01C, 0x020, 0x024, 0x028,
          0x02C, 0x044,
          0x100, 0x104, 0x110, 0x114, 0x118, 0x11C, 0x120, 0x124, 0x128,
          0x12C, 0x144]),
        ("i2s_tx", 0x43C70000, [0x00, 0x04, 0x08, 0x0C, 0x10, 0x14,
                                0x20, 0x24, 0x28, 0x2C, 0x30, 0x34, 0x38])):
    print("  -- %s" % name)
    try:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        try:
            m = mmap.mmap(fd, 4096, mmap.MAP_SHARED,
                          mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
            for off in offs:
                v = struct.unpack("<I", m[off:off + 4])[0]
                print("     0x%03X = 0x%08X" % (off, v))
            m.close()
        finally:
            os.close(fd)
    except Exception as e:
        print("     !! %s: %s" % (type(e).__name__, e))
