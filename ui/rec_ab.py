#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单变量 A/B：只改指定寄存器，比较「放音/静音」时 ADC 数据里 1kHz 分量的比值。

判据：如果 ADC 通路真的通到板载麦克风，放音时 @freq 分量必须显著抬起来。
纯噪声不会跟着放音开关走。

用法:
    sudo python3 rec_ab.py                 # 默认只看 0x03 的几种取值
    sudo python3 rec_ab.py --gain-sweep    # 再加 PGA 增益扫描
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioIn, AudioOut, make_sine, es8388_set_vol   # noqa: E402
from rec_loop import capture, lr, rms, goertzel, peak_freq    # noqa: E402


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return default


def main():
    freq = arg("--freq", 1000.0, float)
    amp = arg("--amp", 0.9, float)
    secs = arg("--secs", 0.35, float)
    vol = arg("--vol", 30, int)
    gain = "--gain-sweep" in sys.argv

    # 每个配置 = (标签, [(寄存器, 值), ...])
    cfgs = [
        ("0x03=0x59 厂家原值 (bit3=1)", [(0x03, 0x59)]),
        ("0x03=0x51 清bit3        ", [(0x03, 0x51)]),
        ("0x03=0x09 清bit6/4/3    ", [(0x03, 0x09)]),
        ("0x03=0x19 清bit6/4      ", [(0x03, 0x19)]),
        ("0x03=0x0D 清bit6/4/5    ", [(0x03, 0x0D)]),
        ("0x03=0x01 只留bit0      ", [(0x03, 0x01)]),
        ("0x03=0xFD 全断电        ", [(0x03, 0xFD)]),
    ]
    if gain:
        cfgs += [
            ("0x59 + PGA 0x00 (0dB)  ", [(0x03, 0x59), (0x09, 0x00)]),
            ("0x59 + PGA 0x22 (+6dB) ", [(0x03, 0x59), (0x09, 0x22)]),
            ("0x59 + PGA 0x44 (+12dB)", [(0x03, 0x59), (0x09, 0x44)]),
            ("0x59 + PGA 0x66 (+18dB)", [(0x03, 0x59), (0x09, 0x66)]),
        ]

    ai = AudioIn()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ai.fmt_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, vol, 0)

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = make_sine(freq, frames=frames, amp=amp, pack=ao.pack)
    tone_bytes = (tone * 8)[:ao.ring]
    sil_bytes = b"\x00" * ao.ring
    settle = ao.ring / 352800.0 + 0.08

    ai.start()
    ao.start()
    print("[ab] 放音 %.0fHz amp=%.2f vol=%d  录音 ring=%dB  settle=%.0fms"
          % (freq, amp, vol, ai.ring, 1000 * settle))
    print("初始: 0x03=0x%02X 0x09=0x%02X 0x0A=0x%02X 0x0B=0x%02X"
          % (ai.i2c.rd(0x03), ai.i2c.rd(0x09), ai.i2c.rd(0x0A),
             ai.i2c.rd(0x0B)))

    print("\n%-26s %-19s %-19s %-19s" %
          ("配置", "L_RMS 放/静", "R_RMS 放/静", "@%.0fHz 放/静" % freq))
    print("-" * 92)

    try:
        for label, regs in cfgs:
            for r, v in regs:
                ai.i2c.wr(r, v)
            time.sleep(0.05)
            res = {}
            for on in (True, False):
                ao.buf.write(0, (tone_bytes if on else sil_bytes)[:ao.ring])
                time.sleep(settle)
                d = capture(ai, secs)
                ls, rs = lr(d)
                res[on] = (rms(ls), rms(rs), goertzel(ls, freq))
            (lo, ro, go) = res[True]
            (lf, rf, gf) = res[False]
            db = 20 * math.log10(max(1e-9, go) / max(1e-9, gf))
            flag = ""
            if db > 6 and go > 50:
                flag = "  <== 听到放音了!"
            print("%-26s %7.1f/%-9.1f %7.1f/%-9.1f %7.1f/%-9.1f (%+5.1f dB)%s"
                  % (label, lo, lf, ro, rf, go, gf, db, flag))
            print("      -> 0x03=0x%02X 0x09=0x%02X 峰值=%dHz"
                  % (ai.i2c.rd(0x03), ai.i2c.rd(0x09),
                     peak_freq(ls)[0] if lo > 1 else 0))
    finally:
        ao.buf.write(0, sil_bytes)
        time.sleep(0.1)
        ao.stop()
        ai.stop()
        ai.close()
        ao.close()


if __name__ == "__main__":
    main()
