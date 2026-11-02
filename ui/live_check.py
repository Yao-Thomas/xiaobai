#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_check.py —— 在**服务运行中**读关键寄存器（只读，不抢设备）

要回答的问题：服务在放音时，formatter 的 DMA 到底开没开、数据有没有在搬。

  R_CTRL = 0x110  bit0 = CTRL_DMA_EN  （0 = DMA 根本没开）
  R_XFER = 0x128  AUD_XFER_COUNT       （只读，已传字节；不动 = 没搬）
  R_STS  = 0x114  AUD_STS
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import Mem                                      # noqa: E402

m = Mem()


def rd(base, off):
    try:
        return m.rd(base, off)
    except Exception as e:
        return "ERR:%s" % str(e)[:24]


print("=" * 76)
print("服务运行中的关键寄存器（只读）")
print("=" * 76)

R_CTRL = A.MM2S + 0x10      # 0x110
R_STS = A.MM2S + 0x14       # 0x114
R_XFER = A.MM2S + 0x28      # 0x128

print()
print("【formatter MM2S（放音侧）】")
c = rd(A.FMT_BASE, R_CTRL)
print("  R_CTRL (0x110) = %s" % c)
if isinstance(c, int):
    print("    bit0 CTRL_DMA_EN = %d   %s"
          % (c & 1, "★ DMA 没开！这就不可能有声音" if not (c & 1) else "DMA 已开"))
    print("    位宽字段 = %d (4 表示写32位旁路 AES)" % ((c >> 3) & 0x7))
print("  R_STS  (0x114) = %s" % rd(A.FMT_BASE, R_STS))
x1 = rd(A.FMT_BASE, R_XFER)
print("  R_XFER (0x128) = %s" % x1)
time.sleep(1.0)
x2 = rd(A.FMT_BASE, R_XFER)
print("  1 秒后         = %s" % x2)
if isinstance(x1, int) and isinstance(x2, int):
    if x2 > x1:
        print("    ★ 在增长（+%d 字节/秒）-> DMA 在搬数据" % (x2 - x1))
    else:
        print("    ✗ 纹丝不动 -> **DMA 没在搬数据**（放音链路断在这里）")

print()
print("【I2S 时钟】")
print("  TX CORE_CTRL = %s" % rd(A.I2S_BASE, A.I2S_CORE_CTRL))
print("  RX CORE_CTRL = %s" % rd(A.I2S_RX_BASE, A.I2S_CORE_CTRL))
print("  TX I2STIM    = %s" % rd(A.I2S_BASE, A.I2S_I2STIM))
print("  RX I2STIM    = %s" % rd(A.I2S_RX_BASE, A.I2S_I2STIM))

print()
print("【录音侧 formatter】")
print("  R2_CTRL (0x10) = %s" % rd(A.I2S_RX_BASE, 0x10))
print("  R2_XFER (0x28) = %s" % rd(A.I2S_RX_BASE, 0x28))

m.close()
print()
print("★ 判读：R_CTRL bit0 = 0 -> DMA 没开，声音不可能有")
print("        bit0 = 1 但 XFER 不涨 -> DMA 开了但传输停了")
