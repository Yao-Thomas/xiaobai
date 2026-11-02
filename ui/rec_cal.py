#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录音电平标定：扫 ADC PGA 和 0x03，找不削顶的工作点，并验证 L/R 两路。

用法:
    sudo python3 rec_cal.py
    sudo python3 rec_cal.py --amp 0.3 --vol 24
    sudo python3 rec_cal.py --wav /tmp/cap.wav
"""
import sys
import time
import math
import struct

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return default


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


def deinterleave(d):
    ls, rs = [], []
    for i in range(len(d) // 8):
        ls.append(s24(int.from_bytes(d[8 * i:8 * i + 4], "little")))
        rs.append(s24(int.from_bytes(d[8 * i + 4:8 * i + 8], "little")))
    return ls, rs


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def peakf(v, step=200):
    best, bf = -1.0, 0
    f = 200
    while f <= 5000:
        g = goe(v, f)
        if g > best:
            best, bf = g, f
        f += step
    return bf, best


def main():
    freq = arg("--freq", 1000.0, float)
    secs = arg("--secs", 0.5, float)
    amp = arg("--amp", 0.4, float)
    vol = arg("--vol", 24, int)
    wav = arg("--wav", None)

    # 先要大块连续内存，再建播放侧（顺序反了容易碎片化失败）
    cap = RawCap()
    cap.cfg()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, vol, 0)

    lim = 0.9 * cap.ring / 352800.0
    secs = min(secs, lim)

    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x0C),
                 (0x10, 0x00), (0x11, 0x00)):
        i2c.wr(r, v)

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = make_sine(freq, frames=frames, amp=amp, pack=ao.pack)
    tone_bytes = (tone * 8)[:ao.ring]
    sil_bytes = b"\x00" * ao.ring

    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, sil_bytes)
    ao.start()
    time.sleep(0.25)
    print("[cal] ring=%.0fKB 录%.2fs  放音 %.0fHz amp=%.2f vol=%d  满量程=8388607"
          % (cap.ring / 1024.0, secs, freq, amp, vol))

    def once(pga, r03, adcin):
        i2c.wr(0x09, pga)
        i2c.wr(0x03, r03)
        i2c.wr(0x0A, adcin)
        time.sleep(0.2)
        res = {}
        for tag, content in (("静", sil_bytes), ("响", tone_bytes)):
            ao.buf.write(0, content)
            time.sleep(0.30)
            d, rate = cap.grab(secs)
            ls, rs = deinterleave(d)
            res[tag] = (rms(ls), rms(rs), goe(ls, freq), goe(rs, freq), ls, rs)
        return res

    print("\n0x03   PGA    静L_RMS   静R_RMS   响L_RMS   响R_RMS  "
          "静@1k    响@1k   比值dB  峰值Hz  削顶%")
    print("-" * 104)
    saved = None
    for r03 in (0x59, 0x19, 0x09):
        for pga in (0x66, 0x44, 0x33, 0x22, 0x11, 0x00):
            r = once(pga, r03, 0x00)
            sl, sr, sgl, sgr, _, _ = r["静"]
            tl, tr, tgl, tgr, tls, trs = r["响"]
            db = 20 * math.log10(max(1e-9, tgl) / max(1e-9, sgl))
            clip = 100.0 * sum(1 for x in tls if abs(x) > 8300000) / max(1, len(tls))
            pf, _ = peakf(tls)
            print("0x%02X  0x%02X  %9.1f %9.1f %9.1f %9.1f  %8.1f %8.1f  %+6.1f  "
                  "%6d  %5.1f"
                  % (r03, pga, sl, sr, tl, tr, sgl, tgl, db, pf, clip))
            if r03 == 0x19 and pga == 0x33 and saved is None:
                saved = (tls, trs, freq)
    print("\n(PGA 3dB/step: 0x00=0dB 0x11=+3 0x22=+6 0x33=+9 0x44=+12 0x66=+18)")

    if wav and saved:
        ls, rs, f0 = saved
        with open(wav, "wb") as f:
            n = len(ls)
            f.write(b"RIFF" + struct.pack("<I", 36 + 2 * n * 2) + b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, 2, A.FS, A.FS * 4, 4, 16))
            f.write(b"data" + struct.pack("<I", 2 * n * 2))
            for i in range(n):
                f.write(struct.pack("<hh",
                                    max(-32768, min(32767, ls[i] >> 8)),
                                    max(-32768, min(32767, rs[i] >> 8))))
        print("[wav] 已写 %s (%d 帧, %.0fHz 立体声 16bit)" % (wav, n, A.FS))

    ao.buf.write(0, sil_bytes)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
