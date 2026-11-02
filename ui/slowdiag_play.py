#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slowdiag_play.py —— 确认"放音慢 12 倍"的诊断

诊断：poll_pos 实测 DMA 消费 3665 帧/秒，期望 44100，差 12.03 倍。

验证方法：把音频**重采样到 3675 Hz**（= 44100/12），
          再用同样的流式方式播 —— 慢 12 倍之后正好回到正常速度。
          如果这样听起来是对的，诊断就成立。

注意：重采样到 3675 Hz 会丢掉 1837 Hz 以上的频率，
      所以听起来会闷，但**速度和旋律应该正常**。
"""
import math
import struct
import sys
import time
import wave

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402

SRC = "/home/zynq/Music/03_小星星.wav"
TRUE_RATE = 3675.0        # ★ 重采样到这个"实际"速率
TARGET = 44100


def main():
    print("=" * 78)
    print("确认诊断：把音频重采样到 %.0f Hz 再播（补偿慢 12 倍）" % TRUE_RATE)
    print("=" * 78)

    w = wave.open(SRC, "rb")
    ch, sw, r, n = (w.getnchannels(), w.getsampwidth(), w.getframerate(),
                    w.getnframes())
    raw = w.readframes(n)
    w.close()
    print("  源: %d Hz %d声道 %dbit %.2f秒" % (r, ch, sw * 8, n / float(r)))

    s16 = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    if ch == 2:
        mono = [(s16[i] + s16[i + 1]) // 2 for i in range(0, len(s16) - 1, 2)]
    else:
        mono = s16
    print("  单声道样本数: %d" % len(mono))

    # 重采样 44100 -> 3675（每 12 个取 1 个，加简单平均抗混叠）
    step = r / TRUE_RATE
    out_n = int(len(mono) / step)
    rs = []
    for k in range(out_n):
        p = k * step
        i0 = int(p)
        # 12 点平均，简单抗混叠
        acc = 0
        cnt = 0
        for j in range(i0, min(i0 + 12, len(mono))):
            acc += mono[j]
            cnt += 1
        rs.append(acc // max(1, cnt))
    print("  重采样后样本数: %d  (%.2f 秒 @ %.0f Hz)"
          % (len(rs), len(rs) / TRUE_RATE, TRUE_RATE))

    # 归一化
    pk = max(abs(x) for x in rs) or 1
    g = (0.9 * 32767) / float(pk)
    rs = [int(x * g) for x in rs]
    print("  归一化 %.2f 倍 -> 峰值 %d" % (g, max(abs(x) for x in rs)))

    # ★ 关键：这些样本要按 TARGET(44100) 的时长来播，因为 DMA 慢 12 倍
    #   即"名义上"它们是 44100 Hz 的样本，只是内容被拉长了
    #   所以我们把它们当成 44100 Hz 的数据流，DMA 慢 12 倍后实际时长 =
    #   len/44100*12 ≈ len/3675 ✓ 正确
    pcm = bytearray()
    for v in rs:
        b = ((v * 256) & 0xFFFFFF).to_bytes(4, "little")
        pcm += b + b
    pcm = bytes(pcm)
    print("  打包后 %d 字节" % len(pcm))

    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    ao.start()

    ring = ao.ring
    blk_bytes = (ring // 8) * 8
    total = len(pcm)
    # 每块名义时长 = blk_bytes/352800，但实际要慢 12 倍 -> 等 12 倍时间
    nominal = blk_bytes / 352800.0
    wait = nominal * (TARGET / TRUE_RATE)
    print()
    print("  流式播放: %d 块, 每块名义 %.4f 秒 -> 等 %.4f 秒"
          % (total // blk_bytes + 1, nominal, wait))

    pos = 0
    t0 = time.time()
    while pos < total:
        blk = pcm[pos:pos + blk_bytes]
        if len(blk) < blk_bytes:
            blk = blk + b"\x00" * (blk_bytes - len(blk))
        ao.buf.write(0, blk)
        time.sleep(wait)
        pos += blk_bytes
    ao.buf.write(0, b"\x00" * ring)
    dt = time.time() - t0

    try:
        ao.close()
    except Exception:
        pass
    print("  播完，实际耗时 %.1f 秒" % dt)
    print("  （歌曲本身 7.42 秒；慢 12 倍的话应该是 ~89 秒，")
    print("    我们按 %.0f Hz 打包，所以这里 %.1f 秒是预期的）"
          % (TRUE_RATE, len(rs) / TRUE_RATE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
