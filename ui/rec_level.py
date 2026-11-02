#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定放音电平 vs 录音响应的线性区间。

背景: 满量程放音会在 MIC 输入脚上产生串扰，把 ADC 打到削顶（RMS 4.8M=57%FS），
      于是改 PGA 也看不出变化。真实语音场景是**半双工**，LISTEN 时 DAC 是静音的，
      所以只要找到"放音时不过载"的电平即可。

用法: sudo python3 rec_level.py
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402


def chans(data, mode="L"):
    ls, rs = [], []
    for i in range(len(data) // 8):
        ls.append(s24(int.from_bytes(data[8 * i:8 * i + 4], "little")))
        rs.append(s24(int.from_bytes(data[8 * i + 4:8 * i + 8], "little")))
    if mode == "L":
        return ls
    if mode == "R":
        return rs
    if mode == "diff":
        return [(ls[i] - rs[i]) // 2 for i in range(len(ls))]
    return [(ls[i] + rs[i]) // 2 for i in range(len(ls))]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def goe(v, f):
    if len(v) < 64:
        return 0.0
    w = 2.0 * math.pi * f / A.FS
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in v:
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (len(v) / 2.0)


def main():
    freq = 1000.0
    secs = 0.4
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    secs = min(secs, 0.8 * cap.ring / 352800.0)

    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x59), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x0C), (0x10, 0x00), (0x11, 0x00)):
        i2c.wr(r, v)

    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.start()
    print("[lvl] ring=%d 录%.2fs 满量程=8388607  PGA=0x66(+18dB)" % (cap.ring, secs))

    def grab():
        cap.cfg()
        d, rate = cap.grab(secs)
        return chans(d), rate

    # 地板：完全不放音（DAC 输出全 0）
    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.35)
    q, qr = grab()
    qg = goe(q, freq)
    print("\n%-22s %10s %10s %10s %8s" % ("配置", "L_RMS", "@1kHz", "峰值", "相对地板"))
    print("-" * 70)
    print("%-22s %10.1f %10.1f %10d %7.1f dB"
          % ("DAC 静音(地板)", rms(q), qg, max(abs(x) for x in q),
             0.0))

    for amp, vol in ((0.9, 30), (0.5, 30), (0.3, 30), (0.2, 24),
                     (0.12, 20), (0.06, 16), (0.9, 8), (0.9, 4)):
        es8388_set_vol(ao.i2c, vol, 0)
        frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
        tone = make_sine(freq, frames=frames, amp=amp, pack=ao.pack)
        ao.buf.write(0, (tone * 8)[:ao.ring])
        time.sleep(0.35)
        v, rate = grab()
        r_, g_ = rms(v), goe(v, freq)
        pk = max(abs(x) for x in v)
        print("%-22s %10.1f %10.1f %10d %7.1f dB   削顶=%s"
              % ("amp=%.2f vol=%d" % (amp, vol), r_, g_, pk,
                 20 * math.log10(max(1e-9, g_) / max(1e-9, qg)),
                 "是" if pk > 8300000 else "否"))

    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
