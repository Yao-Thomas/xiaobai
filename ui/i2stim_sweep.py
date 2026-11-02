#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i2stim_sweep.py —— 扫 I2STIM 分频，量出它对放音速率的影响

背景（本轮实测）：
    配置全对（I2STIM=4, MCLK_RATIO=384, 32bit×2ch），
    但 DMA 实际只消费 **3665 帧/秒**，期望 44100 —— 慢 12.03 倍。
    反推 MCLK = 3665×384 = 1.407 MHz，而应该是 16.9344 MHz。

要回答的问题：**这是分频设大了，还是源时钟本身就慢？**

做法：把 I2STIM 依次设成 1/2/4/8，每次量 DMA 消费速率。
    * 若 I2STIM=1 时能到 44100  -> 分频问题，改常量即可
    * 若 I2STIM=1 仍远低于 44100 -> 源时钟慢，要动 FPGA/时钟树
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402

print("=" * 80)
print("I2STIM 分频扫描：量放音速率")
print("=" * 80)
print("  期望 44100 帧/秒（MCLK 16.9344MHz / 384）")
print()

ao = AudioOut()
ao.codec_up()
ao.i2s_config()
ao.fmt_config()
es8388_set_vol(ao.i2c, 20, 0)
ao.start()

mem = ao.mem


def rate(settle=0.35, span=1.2):
    """量 DMA 消费速率（帧/秒）"""
    time.sleep(settle)
    p1 = ao.poll_pos()
    t1 = time.time()
    time.sleep(span)
    p2 = ao.poll_pos()
    t2 = time.time()
    dt = t2 - t1
    # poll_pos 返回元组，取第一个（字节或帧）
    a1 = p1[0] if isinstance(p1, tuple) else p1
    a2 = p2[0] if isinstance(p2, tuple) else p2
    return (a2 - a1) / dt, p1, p2, dt


print("  %-10s %-14s %-14s %-12s %s"
      % ("I2STIM", "速率(单位/秒)", "折算帧/秒", "vs 期望", "说明"))
print("-" * 80)

base = None
for div in (4, 2, 1, 8, 3):
    # 同时改 TX 和 RX（BCLK = AND(两者)，必须一致）
    ao._i2s_w(A.I2S_I2STIM, div)
    ao._rx_w(A.I2S_I2STIM, div)
    # 重新使能一次，确保生效
    ao._rx_w(A.I2S_CORE_CTRL, 1)
    ao._i2s_w(A.I2S_CORE_CTRL, 1)
    time.sleep(0.2)

    r, p1, p2, dt = rate()
    # 判断单位：若速率接近 352800 则是字节，接近 44100 则是帧
    frames = r / 8.0        # 先按"单位=字节"折算
    ratio = frames / 44100.0
    note = ""
    if div == 4:
        base = r
    elif base and base > 0:
        note = "相对 div=4: %.2f 倍" % (r / base)
    print("  %-10d %-14.0f %-14.0f %-12.3f %s"
          % (div, r, frames, ratio, note))

    # 读回确认
    txv = mem.rd(A.I2S_BASE, A.I2S_I2STIM)
    rxv = mem.rd(A.I2S_RX_BASE, A.I2S_I2STIM)
    if txv != div or rxv != div:
        print("       ⚠ 写 %d 但读回 TX=%s RX=%s" % (div, txv, rxv))

# 恢复
ao._i2s_w(A.I2S_I2STIM, A.I2S_DIV)
ao._rx_w(A.I2S_I2STIM, A.I2S_DIV)
ao.buf.write(0, b"\x00" * ao.ring)
time.sleep(0.2)
try:
    ao.close()
except Exception:
    pass

print()
print("=" * 80)
print("判读")
print("=" * 80)
print("  * 若 div 变小、速率**成比例变大**，说明 I2STIM 是有效分频")
print("  * 若最小的 div=1 仍到不了 44100 -> **源时钟（MCLK）本身就慢**，")
print("    得去查 FPGA 设计里 I2S 的时钟源，改分频救不回来")
print("  * 若 div=1 能到 44100 -> 只要把 I2S_DIV 常量改成 1 即可")
