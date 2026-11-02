#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_clk_probe.py —— 时钟链决定性实验

问题：BCLK = AND(发送器sclk, 接收器sclk)，这两个 sclk 是不是同频同相？
      如果不同相，相与之后可能是"窄脉冲"甚至恒 0 → codec 收不到 BCLK
      → ADC 不吐数据 → 录到全 0（我们看到的正是全 0）。

做法：
  1. 扫【接收器】的 I2STIM(0x20)，看 S2MM 的字节速率跟不跟着变
     - 跟着变  -> 接收器自己的 sclk 在主导
     - 不变    -> 速率由别的环节掐住
  2. 顺便把两个 IP 的寄存器全打出来
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402


def dump(m, tag, base):
    print("  -- %s (0x%08X)" % (tag, base))
    for off in (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24,
                0x28, 0x2C, 0x30, 0x34):
        try:
            print("       0x%03X = 0x%08X" % (off, m.rd(base, off)))
        except Exception as e:
            print("       0x%03X !! %s" % (off, e))


def measure(a, secs=0.6):
    a.start()
    t_end = time.time() + secs
    while time.time() < t_end:
        a.poll_pos()
        time.sleep(0.03)
    _, tot = a.poll_pos()
    dt = time.time() - a.t0
    a.stop()
    return tot / dt if dt else 0.0


def main():
    a = A.AudioIn(verbose=False)
    try:
        a.codec_adc_up("lin1")
        a.fmt_config()
        print("=" * 74)
        print(" 扫【接收器】分频 I2STIM(0x20)，看 S2MM 字节速率")
        print(" 期望：44100 帧/s x 8 字节 = 352800 B/s")
        print("=" * 74)
        for div in (1, 2, 4, 6, 8, 12, 16, 24, 32, 64):
            a.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
            a.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
            a.mem.wr(A.I2S_RX_BASE, A.I2S_I2STIM, div)
            a.mem.wr(A.I2S_BASE, A.I2S_I2STIM, div)
            a.mem.wr(A.I2S_RX_BASE, A.I2S_CH0, 1)
            a.mem.wr(A.I2S_BASE, A.I2S_CH0, 1)
            a._w(A.R2_CTRL, a._r(A.R2_CTRL) & ~A.CTRL_DMA_EN)
            a.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
            a.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
            a._w(A.R2_CTRL, a._r(A.R2_CTRL) | A.CTRL_DMA_EN)
            a._prev = a._r(A.R2_XFER)
            a._total = 0
            a.t0 = time.time()
            rate = measure(a, 0.6)
            print("   接收器 div=%-3d -> %10.1f B/s   (%8.1f 帧/s, 是 44100 的 %.4f 倍)"
                  % (div, rate, rate / 8.0, rate / 8.0 / A.FS))
        print()
        print("=" * 74)
        print(" 寄存器快照（当前 div 还是最后一个值）")
        print("=" * 74)
        dump(a.mem, "发送器 I2S_TX", A.I2S_BASE)
        dump(a.mem, "接收器 I2S_RX", A.I2S_RX_BASE)
        print("  -- formatter")
        for off in (0x04, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x44):
            print("       0x%03X = 0x%08X" % (off, a.mem.rd(A.FMT_BASE, off)))
    finally:
        a.close()


if __name__ == "__main__":
    main()
