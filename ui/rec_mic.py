#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""半双工场景下的麦克风实测：DAC 全程静音，只录不放。

这才是语音助手真正的工作状态（LISTEN 阶段喇叭不响）。
扫 0x03(mic偏置/输入/ADC使能) x 0x0A(输入选择)，每个配置连测 5 次看可重复性。

用法: sudo python3 rec_mic.py
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402


def chans(data):
    ls, rs = [], []
    for i in range(len(data) // 8):
        ls.append(s24(int.from_bytes(data[8 * i:8 * i + 4], "little")))
        rs.append(s24(int.from_bytes(data[8 * i + 4:8 * i + 8], "little")))
    return ls, rs


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def main():
    secs = 0.35
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 0, 0)          # ★ 输出音量 0 = 最小，喇叭基本不响
    secs = min(secs, 0.8 * cap.ring / 352800.0)

    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x0C),
                 (0x10, 0x00), (0x11, 0x00)):
        i2c.wr(r, v)

    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, b"\x00" * ao.ring)     # 全程静音
    ao.start()
    time.sleep(0.4)
    print("[mic] DAC 全程静音  录 %.2fs x5  ring=%d  满量程=8388607"
          % (secs, cap.ring))
    print("\n%-30s %-22s %-22s" % ("配置", "L_RMS (5次)", "R_RMS (5次)"))
    print("-" * 80)

    def meas(r03, adcin, pga, label):
        i2c.wr(0x03, r03)
        i2c.wr(0x0A, adcin)
        i2c.wr(0x09, pga)
        time.sleep(0.30)
        L, R, pk = [], [], 0
        first = None
        for k in range(5):
            cap.cfg()                      # 每次复位，单次 grab
            d, rate = cap.grab(secs)
            ls, rs = chans(d)
            L.append(rms(ls))
            R.append(rms(rs))
            pk = max(pk, max(abs(x) for x in ls) if ls else 0)
            if first is None:
                first = (ls[:5], rs[:5], rate)
        print("%-30s %-22s %-22s" % (label,
              " ".join("%7.0f" % x for x in L),
              " ".join("%7.0f" % x for x in R)))
        print("%-30s L前5=%s R前5=%s %.0fB/s  L峰=%d"
              % ("", list(first[0]), list(first[1]), first[2], pk))

    print("== 输入选择 (0x03=0x59: LIN1开/RIN1关, mic偏置关) ==")
    for sel, nm in ((0x00, "LIN1/RIN1(麦克风)"), (0x50, "LIN2/RIN2(LINE孔)"),
                    (0x05, "MIC1"), (0x06, "MIC2"), (0xF0, "差分")):
        meas(0x59, sel, 0x66, "0x0A=0x%02X %s" % (sel, nm))

    print("\n== mic 偏置 & 右声道 (麦克风输入 0x0A=0x00) ==")
    for r03, nm in ((0x59, "厂家: L输入/L ADC"),
                    (0x51, "0x51: 清bit3=mic偏置ON"),
                    (0x01, "0x01: 全开+mic偏置ON"),
                    (0x09, "0x09: 全开,偏置关"),
                    (0xFD, "0xFD: ADC全断电(对照)")):
        meas(r03, 0x00, 0x66, "0x%02X %s" % (r03, nm))

    print("\n== PGA 增益 (差分 0xF0, 0x03=0x01) ==")
    for pga in (0x00, 0x11, 0x22, 0x33, 0x44, 0x66):
        meas(0x01, 0xF0, pga, "PGA=0x%02X" % pga)

    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
