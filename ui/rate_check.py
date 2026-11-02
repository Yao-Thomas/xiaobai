#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rate_check.py —— 量 DMA/I2S 的**真实消费速率**

为什么关键：
  「一堆的 do」= 播放环在原地循环。要知道该多久换一次数据，
  必须知道环被消费得多快。

  audio_pl.play_tone() 的注释说它"返回实测帧率"，这里直接用它量。
  对比期望值 44100 帧/秒。
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol, make_sine      # noqa: E402

print("=" * 78)
print("DMA 消费速率实测")
print("=" * 78)
print("  期望: 44100 帧/秒 = 352800 字节/秒（8 字节/帧）")
print()

ao = AudioOut()
ao.codec_up()
ao.i2s_config()
ao.fmt_config()
es8388_set_vol(ao.i2c, 20, 0)
ao.start()

print("  播放环 = %d 字节 = %d 帧 = %.4f 秒"
      % (ao.ring, ao.ring // 8, ao.ring / 352800.0))
print("  period_bytes = %d" % ao.period_bytes)

mem = ao.mem
R_XFER = A.MM2S + 0x28

print()
print("--- 方法1：读 R_XFER（0x128）两次，看增量 ---")
try:
    x1 = mem.rd(A.FMT_BASE, R_XFER)
    t1 = time.time()
    time.sleep(1.5)
    x2 = mem.rd(A.FMT_BASE, R_XFER)
    t2 = time.time()
    dt = t2 - t1
    print("  x1=%s  x2=%s   dt=%.3f s" % (x1, x2, dt))
    if isinstance(x2, int) and isinstance(x1, int):
        d = x2 - x1
        print("  增量 = %d  速率 = %.0f /秒" % (d, d / dt))
        if d > 0:
            print("  如果单位是字节: %.0f 帧/秒  （期望 44100）"
                  % (d / dt / 8))
            print("  如果单位是帧  : %.0f 帧/秒  （期望 44100）" % (d / dt))
except Exception as e:
    print("  读失败:", e)

print()
print("--- 方法2：用 audio_pl 自带的 poll_pos 量（更可信）---")
try:
    p1 = ao.poll_pos()
    t1 = time.time()
    time.sleep(1.5)
    p2 = ao.poll_pos()
    t2 = time.time()
    dt = t2 - t1
    print("  pos: %s -> %s   dt=%.3f" % (p1, p2, dt))
    if isinstance(p2, int) and isinstance(p1, int):
        d = p2 - p1
        # poll_pos 可能返回字节
        print("  增量 = %d -> %.0f /秒" % (d, d / dt))
        print("    若字节: %.0f 帧/秒" % (d / dt / 8))
        print("    若帧  : %.0f 帧/秒" % (d / dt))
except Exception as e:
    print("  poll_pos 失败:", e)

print()
print("--- 方法3：灌一段唯一的斜坡图案，看多久被读完 ---")
try:
    # 环里每个 32bit 字填它的序号（低 24 位），这样能看出读到哪
    frames = ao.ring // 8
    buf = bytearray()
    for i in range(frames):
        v = (i * 37) & 0xFFFFFF
        b = v.to_bytes(4, "little")
        buf += b + b
    ao.buf.write(0, bytes(buf))
    time.sleep(0.5)
    # 读回环内容，看哪些位置被 DMA 改过是不可能的（DMA 只读）
    # 所以改成：看 poll_pos 在环里的推进速度
    q1 = ao.poll_pos()
    time.sleep(1.0)
    q2 = ao.poll_pos()
    print("  1 秒内 poll_pos 推进 = %s" % (q2 - q1 if isinstance(q2, int)
                                          and isinstance(q1, int) else "?"))
    print("  （环大小 %d 字节，若推进 ≈352800 说明速率对）" % ao.ring)
except Exception as e:
    print("  失败:", e)

ao.buf.write(0, b"\x00" * ao.ring)
time.sleep(0.3)
try:
    ao.close()
except Exception:
    pass
print()
print("★ 判读：速率 ≈352800 字节/秒 或 ≈44100 帧/秒 = 正常")
print("        明显更小 = DMA 消费不过来，流式播放必然循环/卡顿")
