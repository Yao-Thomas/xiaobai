#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 read_ring() 单次快照做可信测量，并在同一状态下对比 capture() 增量法。

目的:
  1) 判定到底哪种采集方式可信（两者在同一状态下应给出一致结果）
  2) 扫 ADC 的 FsRatio (0x0D)，找能出真实音频的取值

用法:
    sudo python3 rec_ring.py
    sudo python3 rec_ring.py --ratio        # 只扫 0x0D
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioIn, AudioOut, make_sine, es8388_set_vol   # noqa: E402


def s24(w):
    w &= 0xFFFFFF
    return w - 0x1000000 if w & 0x800000 else w


def stats(data, freq):
    """返回 (L列表, R列表, L_RMS, R_RMS, @freq)"""
    ls, rs = [], []
    for i in range(len(data) // 8):
        ls.append(s24(int.from_bytes(data[8 * i:8 * i + 4], "little")))
        rs.append(s24(int.from_bytes(data[8 * i + 4:8 * i + 8], "little")))
    if not ls:
        return ls, rs, 0.0, 0.0, 0.0
    rl = math.sqrt(sum(float(x) * x for x in ls) / len(ls))
    rr = math.sqrt(sum(float(x) * x for x in rs) / len(rs))
    w = 2.0 * math.pi * freq / A.FS
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in ls:
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    g = math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (len(ls) / 2.0)
    return ls, rs, rl, rr, g


def peak(ls, lo=200, hi=6000, step=50):
    if len(ls) < 64:
        return 0, 0.0
    best, bf = -1.0, 0
    f = lo
    while f <= hi:
        w = 2.0 * math.pi * f / A.FS
        c = 2.0 * math.cos(w)
        s1 = s2 = 0.0
        for x in ls:
            s0 = x + c * s1 - s2
            s2, s1 = s1, s0
        g = math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (len(ls) / 2.0)
        if g > best:
            best, bf = g, f
        f += step
    return bf, best


def snap(ai, freq, n_back=3):
    """取 n_back 次 read_ring 快照，返回中间那次（避开正在被写的边界）"""
    out = []
    for _ in range(n_back):
        out.append(stats(ai.read_ring(), freq))
        time.sleep(0.03)
    return out[len(out) // 2], out


def main():
    freq = 1000.0
    ai = AudioIn()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ai.fmt_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = make_sine(freq, frames=frames, amp=0.9, pack=ao.pack)
    tone_bytes = (tone * 8)[:ao.ring]
    sil_bytes = b"\x00" * ao.ring

    ai.codec_adc_up(adc_in="lin1")
    ai.i2c.wr(0x03, 0x59)

    ai.start()
    ao.start()
    ao.buf.write(0, tone_bytes)          # 一直放着 1kHz 响音
    print("[cfg] 一直放 1kHz amp0.9 vol30  录音 ring=%d" % ai.ring)

    ls, rs, rl, rr, g = snap(ai, freq)[0]
    print("\n[T0] 0x03=0x%02X 0x0D=0x%02X 0x18=0x%02X 0x08=0x%02X 0x2B=0x%02X"
          % (ai.i2c.rd(0x03), ai.i2c.rd(0x0D), ai.i2c.rd(0x18),
             ai.i2c.rd(0x08), ai.i2c.rd(0x2B)))
    print("     前 8 帧: " + " ".join("(%d,%d)" % (ls[i], rs[i]) for i in range(8)))
    print("     L_RMS=%.1f R_RMS=%.1f @%.0fHz=%.1f  峰值=%s"
          % (rl, rr, freq, g, peak(ls)))

    # ---- 同一状态下对比 capture() 增量法 ----
    try:
        from rec_loop import capture, lr, rms, goertzel
        d = capture(ai, 0.35)
        cls, crs = lr(d)
        print("     [对照] capture() 增量法: 样本数=%d L_RMS=%.1f R_RMS=%.1f @%.0fHz=%.1f"
              % (len(cls), rms(cls), rms(crs), freq, goertzel(cls, freq)))
        print("     [对照] capture() 前 8 帧: "
              + " ".join("(%d,%d)" % (cls[i], crs[i]) for i in range(min(8, len(cls)))))
    except Exception as e:
        print("     [对照] capture() 失败: %s" % e)

    # ---- 扫 ADC FsRatio ----
    print("\n================ 扫 ADC FsRatio (0x0D) ================")
    print("0x0D   L_RMS      R_RMS      @1000Hz   峰值Hz   前4帧")
    for v in [0x0C, 0x03, 0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08,
              0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x10, 0x13, 0x18, 0x1F]:
        ai.i2c.wr(0x0D, v)
        time.sleep(0.25)
        (ls, rs, rl, rr, g), _ = snap(ai, freq)
        pf, pg = peak(ls)
        print("0x%02X  %9.1f  %9.1f  %9.1f  %6d   %s"
              % (v, rl, rr, g, pf,
                 " ".join("(%d,%d)" % (ls[i], rs[i]) for i in range(4))))

    ao.buf.write(0, sil_bytes)
    time.sleep(0.2)
    ao.stop()
    ai.stop()
    ai.close()
    ao.close()


if __name__ == "__main__":
    main()
