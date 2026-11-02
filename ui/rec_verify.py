#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判定采集到的到底是不是真 ADC 数据。

判据（都不依赖声学环境）:
  * 改 ADC PGA (0x09)        -> 真数据必须跟着变
  * 改 ADC 数字音量 (0x10/0x11) 0x00=0dB vs 0xC0=-96dB -> 真数据必须变
  * 关掉 ADC 电源 (0x03=0xFD)  -> 真数据必须变成静音/恒定

采集方式统一为: **每次测量前 cap.cfg()，单次 grab，绝不复用 DMA**。
（之前 rec_big 多 trial 复用 DMA 得到的 4.8M 很可能是假象）

用法: sudo python3 rec_verify.py
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
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
    freq = 1000.0
    secs = 0.35
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)
    secs = min(secs, 0.8 * cap.ring / 352800.0)

    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x0C)):
        i2c.wr(r, v)

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = make_sine(freq, frames=frames, amp=0.9, pack=ao.pack)
    tone_bytes = (tone * 8)[:ao.ring]
    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, tone_bytes)        # 一直放 1kHz
    ao.start()
    time.sleep(0.4)
    print("[verify] ring=%d  录 %.2fs  一直放 %.0fHz amp0.9 vol30"
          % (cap.ring, secs, freq))

    def measure(regs, label):
        for r, v in regs:
            i2c.wr(r, v)
        time.sleep(0.30)
        out = []
        for k in range(3):
            cap.cfg()                    # ★ 每次都复位，单次 grab
            d, rate = cap.grab(secs)
            ls, rs = chans(d)
            out.append((rms(ls), rms(rs), rate, ls[:6], rs[:6]))
        r0 = out[0]
        print("%-30s L_RMS %8.1f %8.1f %8.1f | R_RMS %7.1f %7.1f %7.1f | %.0fB/s"
              % (label, out[0][0], out[1][0], out[2][0],
                 out[0][1], out[1][1], out[2][1], r0[2]))
        print("%-30s   前6帧 L=%s" % ("", list(r0[3])))
        print("%-30s   前6帧 R=%s" % ("", list(r0[4])))
        return out

    print("\n--- A. 基准 (厂家值) ---")
    measure([(0x03, 0x59), (0x09, 0x66), (0x0A, 0x00),
             (0x10, 0x00), (0x11, 0x00)], "基准 0x03=59 PGA=66 0x0A=00")

    print("\n--- B. 改 ADC PGA (0x09) ---")
    for pga in (0x00, 0x11, 0x22, 0x33, 0x44, 0x66):
        measure([(0x09, pga)], "PGA=0x%02X" % pga)

    print("\n--- C. 改 ADC 数字音量 (0x10/0x11) ---")
    for v in (0x00, 0x40, 0x80, 0xC0):
        measure([(0x09, 0x66), (0x10, v), (0x11, v)],
                "ADC数字音量=0x%02X" % v)

    print("\n--- D. 改 ADC 输入选择 (0x0A) ---")
    for sel, nm in ((0x00, "LIN1/RIN1"), (0x50, "LIN2/RIN2"),
                    (0x05, "MIC1"), (0x06, "MIC2"), (0xF0, "差异")):
        measure([(0x10, 0x00), (0x11, 0x00), (0x0A, sel)],
                "0x0A=0x%02X (%s)" % (sel, nm))

    print("\n--- E. 关 ADC 电源 (0x03) ---")
    for v in (0x59, 0x01, 0x09, 0xFD):
        measure([(0x0A, 0x00), (0x03, v)], "0x03=0x%02X" % v)

    print("\n提示: 若 A~E 全都给出几乎相同的数值 -> 采到的不是 ADC 数据，"
          "而是 I2S 接收器在数据线不翻转时吐出的固定图案。")

    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
