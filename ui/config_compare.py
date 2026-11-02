#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_compare.py —— 对比几套**完整**的 ES8388 配置，找稳定可复现的那套。

动机（本轮新发现）：厂家驱动里有**两套**完全不同的寄存器配置：
  我们一直用的（来自他的初始化表）:
      0x00=0x06 0x0C=0x00 0x0D=0x0C 0x18=0x03 0x1A/1B=0x00 0x27/2A=0xF8 0x03=0x59
  他另一处（录音/播放的具体配置）:
      0x00=0x36 0x0C=0x0C 0x0D=0x02 0x18=0x02 0x1A/1B=0x0a 0x27/2A=0xB8
      0x35=0xA0 0x03=0x09

我们的 MCLK/fs = 16934400/44100 = 384，所以 0x0D/0x18 的"正确"值是 0x03。
之前 sweep 0x0D 是在麦克风偏置修好**之前**做的（ADC 本来就没数据），结论作废。

判据（两个都要好）：
  * 稳定：多次"静音"RMS 的相对抖动小
  * 有信号：放 990.5Hz 时该频点能量显著高于静音

用法: sudo systemctl stop zynq-audio; sudo python3 config_compare.py
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402
from audio_svc import goe                                     # noqa: E402

FS = A.FS
F0 = 990.53          # 无缝：2048 帧里正好 46 个周期
SECS = 0.40
REPS = 4


def left(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


# ---- 基础（两边都一样的部分）----
BASE = {0x08: 0x00, 0x01: 0x50, 0x02: 0x00, 0x0B: 0x02,
        0x09: 0x66, 0x0A: 0x00, 0x10: 0x00, 0x11: 0x00,
        0x03: 0x51, 0x2B: 0x80}

def M(extra):
    d = dict(BASE)
    d.update(extra)
    return d


CONFIGS = [
    ("A 当前(厂家表) 0x0D=0C 0x0C=00 0x18=03",
     M({0x00: 0x06, 0x0C: 0x00, 0x0D: 0x0C, 0x18: 0x03,
                   0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8})),
    ("B 当前 + 0x0D=03 (384) ★理论正确",
     M({0x00: 0x06, 0x0C: 0x00, 0x0D: 0x03, 0x18: 0x03,
                   0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8})),
    ("C 当前 + 0x0D=02 (256)",
     M({0x00: 0x06, 0x0C: 0x00, 0x0D: 0x02, 0x18: 0x03,
                   0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8})),
    ("D 厂家另一套 0x0D=02 0x0C=0C",
     M({0x00: 0x36, 0x0C: 0x0C, 0x0D: 0x02, 0x18: 0x02,
                   0x1A: 0x0A, 0x1B: 0x0A, 0x27: 0xB8, 0x2A: 0xB8})),
    ("E D 但 0x0D=03/0x18=03 (384)",
     M({0x00: 0x36, 0x0C: 0x0C, 0x0D: 0x03, 0x18: 0x03,
                   0x1A: 0x0A, 0x1B: 0x0A, 0x27: 0xB8, 0x2A: 0xB8})),
    ("F B + 0x0C=0C (16bit)",
     M({0x00: 0x06, 0x0C: 0x0C, 0x0D: 0x03, 0x18: 0x03,
                   0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8})),
]


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    secs = min(SECS, 0.8 * cap.ring / 352800.0)
    i2c = cap.i2c
    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, b"\x00" * ao.ring)
    ao.start()

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = (make_sine(F0, frames=frames, amp=0.9, pack=ao.pack) * 8)[:ao.ring]
    silence = b"\x00" * ao.ring

    def rec():
        cap.cfg()
        cap.grab(0.08)
        cap.cfg()
        d, _ = cap.grab(secs)
        return left(d)

    def apply(regs):
        for r, v in regs.items():
            try:
                i2c.wr(r, v)
            except Exception as e:
                print("     写 0x%02X 失败: %s" % (r, e))
        time.sleep(0.35)

    print("=" * 96)
    print("config_compare  ring=%d 录%.2fs  MCLK/fs=16934400/44100=384"
          % (cap.ring, secs))
    print("=" * 96)
    print("%-36s %-26s %-22s %s" %
          ("配置", "静音RMS x%d" % REPS, "放音@990能量 x%d" % REPS, "抖动/增益"))
    print("-" * 96)
    best = None
    for label, regs in CONFIGS:
        ao.buf.write(0, silence)
        time.sleep(0.35)
        apply(regs)
        rec()                                  # 丢掉配置后的暂态
        offs, ons = [], []
        for k in range(REPS):
            ao.buf.write(0, silence)
            time.sleep(ao.ring / 352800.0 + 0.10)
            v = rec()
            offs.append(rms(v))
            ao.buf.write(0, tone)
            time.sleep(ao.ring / 352800.0 + 0.10)
            v = rec()
            ons.append(goe(v, F0))
        mo = sum(offs) / len(offs)
        jit = (max(offs) - min(offs)) / max(1e-9, mo)
        g = sum(ons) / len(ons)
        # 静音的 990 能量基线
        ao.buf.write(0, silence)
        time.sleep(ao.ring / 352800.0 + 0.10)
        gq = goe(rec(), F0)
        db = 20 * math.log10(max(1e-9, g) / max(1e-9, gq))
        flag = ""
        if jit < 0.35 and db > 12:
            flag = "  ★ 又稳又有信号"
            if best is None or db > best[1]:
                best = (label, db)
        print("%-36s %-26s %-22s 抖动%.2f 增益%+.1f dB%s"
              % (label, " ".join("%6.0f" % x for x in offs),
                 " ".join("%7.0f" % x for x in ons), jit, db, flag))
        print("     静音@990基线=%.1f   0x0D=0x%02X 0x0C=0x%02X 0x00=0x%02X"
              % (gq, i2c.rd(0x0D), i2c.rd(0x0C), i2c.rd(0x00)))

    print("-" * 96)
    if best:
        print("★ 最佳配置: %s   增益 %+.1f dB" % best)
    else:
        print("⚠ 没有任何一套同时满足(抖动<0.35 且 增益>12dB)")

    ao.buf.write(0, silence)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
