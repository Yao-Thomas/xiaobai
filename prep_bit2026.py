#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prep_bit2026.py —— 把 2026.1 的 .bit 转成两种格式, 供 u-boot 测试

u-boot 的 boot.scr 里这段:
    if test -e ... /system.bit; then
        fatload ... system.bit;
        fpga loadb 0 ${fileaddr} ${filesize}
    fi
`fpga loadb` 要的是"binary bitstream"。两种可能的格式:
    raw     : 00 00 00 BB ...   (.bit 去掉文本头)
    swapped : BB 00 00 00 ...   (按 4 字节反转, Linux FPGA Manager 要这个)
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.runs\impl_1\system_wrapper.bit"
SYNC = b"\x00\x00\x00\xbb"


def conv(src, dst, swap):
    data = open(src, "rb").read()
    off = data.find(SYNC)
    if off < 0:
        print("  ❌ 找不到同步字"); return False
    raw = bytearray(data[off:])
    if len(raw) % 4:
        raw += b"\x00" * (4 - len(raw) % 4)
    if swap:
        for i in range(0, len(raw), 4):
            raw[i], raw[i+3] = raw[i+3], raw[i]
            raw[i+1], raw[i+2] = raw[i+2], raw[i+1]
    open(dst, "wb").write(bytes(raw))
    print("  %s  %d 字节  开头=%s  %s" %
          (os.path.basename(dst), len(raw), raw[:8].hex(),
           "(swapped)" if swap else "(raw)"))
    return True


print("源: %s (%d 字节)" % (SRC, os.path.getsize(SRC)))
print("转换:")
conv(SRC, r"D:\ubuntu_iso\gpu2026_raw.bit", False)
conv(SRC, r"D:\ubuntu_iso\gpu2026_swapped.bit", True)
print("✅ 完成")
