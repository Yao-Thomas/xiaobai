#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_plmem.py —— 测试从 Linux 直接读写 PL 寄存器 (/dev/mem)
   读几个已知的 PL 外设地址, 验证访问通道
"""
import mmap, os, struct, sys

PAGE = 4096
TARGETS = [
    ("GPIO0  @0x41200000", 0x41200000),
    ("GPIO1  @0x41210000", 0x41210000),
    ("PWM    @0x43c00000", 0x43c00000),
    ("I2C    @0x41600000", 0x41600000),
]

def rd32(fd, addr):
    base = addr & ~(PAGE - 1)
    off = addr - base
    mm = mmap.mmap(fd, PAGE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
    v = struct.unpack("<I", mm[off:off + 4])[0]
    mm.close()
    return v

def main():
    print("=== /dev/mem 是否存在 ===")
    print("  ", os.path.exists("/dev/mem"), os.stat("/dev/mem").st_mode if os.path.exists("/dev/mem") else "")
    try:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    except Exception as ex:
        print("打不开 /dev/mem:", ex)
        return
    print("  打开成功 ✅")
    print("")
    print("=== 读 PL 寄存器 ===")
    for name, addr in TARGETS:
        try:
            v = rd32(fd, addr)
            print("  %-22s = 0x%08X" % (name, v))
        except Exception as ex:
            print("  %-22s 读取失败: %s" % (name, ex))
    os.close(fd)
    print("")
    print("PLMEM_DONE")

main()
