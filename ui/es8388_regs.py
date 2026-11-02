#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_regs.py —— 把 ES8388 全部寄存器读出来（跑在板子上）

用法:
    python3 es8388_regs.py            只读
    python3 es8388_regs.py init       先按我们的表初始化再读
"""
import sys

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402

i2c = A.I2C()
try:
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        A.es8388_init(i2c)
        print("已按我们的初始化表配置")

    print("=" * 66)
    print(" ES8388 全部寄存器 (0x00 - 0x34)")
    print("=" * 66)
    for base in range(0, 0x35, 0x10):
        row = []
        for r in range(base, min(base + 0x10, 0x35)):
            try:
                row.append("%02X:%02X" % (r, i2c.rd(r)))
            except Exception:
                row.append("%02X:??" % r)
        print("  " + "  ".join(row))
finally:
    i2c.close()
