#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dma_check.py —— 决定性诊断：DMA 到底有没有在搬数据

思路：
  1. 灌一段纯音进播放环
  2. 读 MM2S 的传输计数寄存器（R_XFER = MM2S + 0x28）
  3. 等 1 秒再读 -> 计数应该涨（说明 DMA 在搬）
  4. 顺便看环内容是否被读走（消费速度）

  计数在涨 + 没声音  -> 数字侧在跑，问题在模拟侧（功放/喇叭）
  计数不动         -> DMA 压根没启动，问题在 PL/驱动
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402

F0 = 990.5


def main():
    print("=" * 76)
    print("DMA 诊断：MM2S 到底有没有在搬数据")
    print("=" * 76)

    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    mem = ao.mem

    R_XFER = A.MM2S + 0x28
    print("  寄存器: MM2S 基址=0x%08X  R_XFER 偏移=0x%02X (绝对 0x%08X)"
          % (A.MM2S, 0x28, A.MM2S + 0x28))
    print("  播放环 = %d 字节 (%.3f 秒)"
          % (ao.ring, ao.ring / 352800.0))

    def xfer():
        try:
            return mem.rd(A.FMT_BASE, R_XFER)
        except Exception as e:
            return "读失败:%s" % e

    silence = b"\x00" * ao.ring
    frames = max(64, ao.period_bytes // 8)
    tone = (make_sine(F0, frames=frames, amp=0.6, pack=ao.pack) * 8)

    print()
    print("--- 1) 先灌静音，看计数动不动 ---")
    ao.buf.write(0, silence)
    time.sleep(0.6)
    x0 = xfer()
    print("    x0 = %s" % x0)
    time.sleep(1.0)
    x1 = xfer()
    print("    x1 = %s   (1 秒后)" % x1)
    try:
        print("    增量 = %d" % (x1 - x0))
    except Exception:
        pass

    print()
    print("--- 2) 灌纯音，看计数涨不涨（1.5 秒）---")
    ao.buf.write(0, tone[:ao.ring])
    time.sleep(0.3)
    x2 = xfer()
    print("    x2 = %s" % x2)
    for k in range(3):
        time.sleep(0.5)
        x3 = xfer()
        print("    +%.1fs  x = %s" % (0.5 * (k + 1), x3))

    print()
    print("--- 3) 看环里现在还有没有内容（DMA 读走的话会被覆盖吗）---")
    raw = ao.buf.read(0, 64)
    nonzero = sum(1 for b in raw if b)
    print("    环头部 64 字节里非零的有 %d 个" % nonzero)

    print()
    print("--- 4) 顺便确认 PL 几个关键寄存器 ---")
    for name, base, off in (("TX CORE_CTRL", A.I2S_BASE, A.I2S_CORE_CTRL),
                            ("RX CORE_CTRL", A.I2S_RX_BASE, A.I2S_CORE_CTRL)):
        print("    %-14s = %s" % (name, mem.rd(base, off)))
    for off, n in ((0x00, "MM2S DMACR"), (0x04, "MM2S DMASR"),
                   (0x28, "MM2S XFER")):
        try:
            print("    %-14s (0x%02X) = 0x%08X"
                  % (n, off, mem.rd(A.MM2S, off)))
        except Exception as e:
            print("    %-14s 读失败 %s" % (n, e))

    ao.buf.write(0, silence)
    time.sleep(0.2)
    ao.close()
    print()
    print("★ 判读：灌纯音后 XFER 计数如果明显增长 -> DMA 在搬")
    print("        如果纹丝不动 -> DMA 没启动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
