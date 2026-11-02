#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦克风输入模式对比：单端(0x00) vs 差分(0xF0)，以及 0x03 各组合。

板子原理图: MIC_P -> LIN1(pin24), MIC_N -> RIN1(pin23) —— 是差分麦克风。
0x0A=0x00 把 LIN1/RIN1 当两个单端输入（这时 L 和 R 是反相的，相减可恢复信号）
0x0A=0xF0 让芯片内部做差分（更好：共模抑制、幅度翻倍）

用法: sudo python3 rec_cal2.py
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap                                    # noqa: E402
from rec_cal import deinterleave, rms, goe, peakf             # noqa: E402


def main():
    freq = 1000.0
    amp = 0.9
    vol = 30
    secs = 0.45

    cap = RawCap()
    cap.cfg()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, vol, 0)
    secs = min(secs, 0.85 * cap.ring / 352800.0)
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

    cfg = [
        ("单端  LIN1/RIN1", 0x59, 0x00, 0x66),
        ("差分  DIFFERENCE", 0x59, 0xF0, 0x66),
        ("两端  0x09 单端", 0x09, 0x00, 0x66),
        ("两端  0x09 差分", 0x09, 0xF0, 0x66),
        ("全开 0x01 单端", 0x01, 0x00, 0x66),
        ("全开 0x01 差分", 0x01, 0xF0, 0x66),
        ("差分  0x09 +12dB", 0x09, 0xF0, 0x44),
        ("差分  0x01 +12dB", 0x01, 0xF0, 0x44),
    ]
    print("[cal2] ring=%.0fKB 录%.2fs 放音%.0fHz amp%.2f vol%d"
          % (cap.ring / 1024.0, secs, freq, amp, vol))
    print("\n%-18s %-5s %-5s  %-19s %-19s %-17s" %
          ("配置", "0x03", "0x0A", "静 (L,R,差) RMS", "响 (L,R,差) RMS",
           "@1k 静->响 (差)"))
    print("-" * 104)
    for label, r03, adcin, pga in cfg:
        i2c.wr(0x03, r03)
        i2c.wr(0x0A, adcin)
        i2c.wr(0x09, pga)
        time.sleep(0.2)
        res = {}
        for tag, content in (("静", sil_bytes), ("响", tone_bytes)):
            ao.buf.write(0, content)
            time.sleep(0.30)
            d, _ = cap.grab(secs)
            ls, rs = deinterleave(d)
            df = [(ls[i] - rs[i]) // 2 for i in range(len(ls))]
            res[tag] = (rms(ls), rms(rs), rms(df), goe(df, freq), df)
        sl, sr, sd, sg, sdf = res["静"]
        tl, tr, td, tg, tdf = res["响"]
        db = 20 * math.log10(max(1e-9, tg) / max(1e-9, sg))
        pf, _ = peakf(tdf)
        print("%-18s 0x%02X  0x%02X   %6.0f %6.0f %7.0f   %6.0f %6.0f %7.0f   "
              "%7.1f->%-7.1f %+5.1f dB  峰值%dHz"
              % (label, r03, adcin, sl, sr, sd, tl, tr, td, sg, tg, db, pf))

    ao.buf.write(0, sil_bytes)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
