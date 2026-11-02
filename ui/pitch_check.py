#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pitch_check.py —— 量**实际听到的音高**（最独立的判据）

不依赖任何寄存器解读：
    放一个已知频率的纯音 -> 麦克风回录 -> 扫频找峰值 -> 看它落在哪

  若 1000 Hz 放出来是 ~1000 Hz -> 放音速率正常，之前"慢12倍"的判断错了
  若 1000 Hz 放出来是 ~83 Hz   -> 慢 12 倍坐实

做法用"一次性写满环"（已知能出声的那条路），排除流式的干扰。
"""
import math
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
PLAY_F = 1000.0


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def goe(v, f, rate=FS):
    n = len(v)
    if n < 64:
        return 0.0
    c = 2.0 * math.cos(2.0 * math.pi * f / rate)
    s1 = s2 = 0.0
    for i, x in enumerate(v):
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        s0 = x * w + c * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def main():
    print("=" * 80)
    print("音高实测：放 %.0f Hz，看麦克风收到多少 Hz" % PLAY_F)
    print("=" * 80)

    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    ao.start()

    cap = RawCap(verbose=False)
    i2c = cap.i2c
    for r, v in [(0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x02), (0x10, 0x00), (0x11, 0x00),
                 (0x18, 0x03), (0x2B, 0x80)]:
        i2c.wr(r, v)
    time.sleep(0.4)
    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    frames = max(64, ao.period_bytes // 8)
    ring = ao.ring
    silence = b"\x00" * ring

    # ---- 基线 ----
    ao.buf.write(0, silence)
    time.sleep(0.5)
    cap.cfg()
    v0, _ = cap.grab(0.6)
    base = left_of(v0)

    # ---- 放 1000 Hz，一次性写满环 ----
    tone = (make_sine(PLAY_F, frames=frames, amp=0.9, pack=ao.pack) * 8)
    ao.buf.write(0, tone[:ring])
    time.sleep(0.35)
    cap.cfg()
    v1, _ = cap.grab(0.6)
    play = left_of(v1)

    ao.buf.write(0, silence)
    time.sleep(0.25)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    if not play:
        print("  没采到数据")
        return 1

    # ---- 扫频找峰值 ----
    # 从 50 Hz 到 3000 Hz 对数扫，粗扫 60 个点，再细扫
    def scan(freqs):
        best, bf = 0.0, 0.0
        for f in freqs:
            e = goe(play, f)
            if e > best:
                best, bf = e, f
        return bf, best

    coarse = [50 * (1.06 ** i) for i in range(80) if 50 * (1.06 ** i) < 3000]
    f0, _ = scan(coarse)
    fine = [f0 * (0.94 + 0.12 * i / 40.0) for i in range(41)]
    best_f, best_e = scan(fine)

    base_e = goe(base, best_f)
    play_e = goe(play, best_f)

    print()
    print("  峰值频率       = %.1f Hz" % best_f)
    print("  该频点能量     : 基线 %.3g  ->  放音 %.3g" % (base_e, play_e))
    if base_e > 0:
        print("  提升           = %+.1f dB"
              % (10 * math.log10(max(1e-9, play_e) / max(1e-9, base_e))))
    print()
    print("  我放的是       = %.1f Hz" % PLAY_F)
    print("  实测峰值       = %.1f Hz" % best_f)
    if best_f > 0:
        print("  实际/标称      = %.4f" % (best_f / PLAY_F))
        if abs(best_f - PLAY_F) / PLAY_F < 0.15:
            print()
            print("  ★ 音高正确 —— 放音速率没问题！")
            print("    那之前 poll_pos 量出的 3665/秒 是我解读错了")
            print("    （poll_pos 会回绕，而且单位不明确）")
        else:
            print()
            print("  ★ 音高不对：实际是标称的 %.3f 倍" % (best_f / PLAY_F))
            print("    与放音速率慢12倍的推断方向一致（若比值≈0.083）")
    print()
    print("  ★ 注：这个测试会出声（1000Hz 或它变调后的频率）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
