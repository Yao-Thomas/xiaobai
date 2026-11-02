#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""matrix_repeat.py —— 用最稳的那套配置，把频谱矩阵**连跑 3 次**，验证可复现性。

目标（objective 明确要求"每阶段要有可复现的真机证据"）：
    同一台机器、同一份代码、同一套寄存器，连续跑 3 次矩阵，
    对角线命中数和增益必须**基本一致**。

配置来自 config_compare.py 的结论：0x0D=0x02 抖动最小(0.31)。
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
SECS = 0.5
RUNS = 3

# ★ config_compare 选出的最稳配置
CFG = {0x08: 0x00, 0x01: 0x50, 0x02: 0x00, 0x0B: 0x02,
       0x09: 0x66, 0x0A: 0x00, 0x10: 0x00, 0x11: 0x00,
       0x03: 0x51, 0x2B: 0x80,
       0x00: 0x06, 0x0C: 0x00, 0x0D: 0x02, 0x18: 0x03,
       0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8}


def left(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    secs = min(SECS, 0.8 * cap.ring / 352800.0)
    i2c = cap.i2c
    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, b"\x00" * ao.ring)
    ao.start()

    def apply():
        for r, v in CFG.items():
            i2c.wr(r, v)
        time.sleep(0.35)

    def rec():
        cap.cfg()
        cap.grab(0.08)
        cap.cfg()
        d, _ = cap.grab(secs)
        return left(d)

    def alive():
        v = rec()
        return math.sqrt(sum(float(x) * x for x in v) / max(1, len(v)))

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    ks = [23, 30, 46, 60, 70, 93]
    freqs = [round(k * float(FS) / frames, 2) for k in ks]

    print("=" * 88)
    print("matrix_repeat  配置: 0x0D=0x02 0x03=0x51 0x09=0x66  (ring=%d, 录%.2fs)"
          % (cap.ring, secs))
    print("=" * 88)
    results = []
    for run in range(1, RUNS + 1):
        apply()
        r0 = alive()
        # 静音基线
        ao.buf.write(0, b"\x00" * ao.ring)
        time.sleep(ao.ring / 352800.0 + 0.12)
        base = [goe(rec(), f) for f in freqs]
        rows = []
        for f0 in freqs:
            tone = (make_sine(f0, frames=frames, amp=0.9, pack=ao.pack) * 8)[:ao.ring]
            ao.buf.write(0, tone)
            time.sleep(ao.ring / 352800.0 + 0.12)
            v = rec()
            e = [goe(v, f) for f in freqs]
            top = e.index(max(e))
            rows.append((f0, e, top, freqs.index(f0) == top,
                         20 * math.log10(max(1e-9, e[top]) / max(1e-9, base[top]))))
        hit = sum(1 for r in rows if r[3])
        gains = [r[4] for r in rows]
        results.append((hit, sum(gains) / len(gains), min(gains), max(gains), r0))
        print("\n--- 第 %d 次 ---  ADC存活RMS=%.0f" % (run, r0))
        print("%-9s | %s | 判定" % ("播放Hz", " ".join("%9.0f" % f for f in freqs)))
        for f0, e, top, ok, db in rows:
            print("%-9.1f | %s | %s (%+.1f dB)"
                  % (f0, " ".join("%9.0f" % x for x in e),
                     "★" if ok else "偏离→%.1f" % freqs[top], db))
        print("   命中 %d/%d   平均增益 %+.1f dB  (最小 %+.1f, 最大 %+.1f)"
              % (hit, len(freqs), sum(gains) / len(gains),
                 min(gains), max(gains)))
        ao.buf.write(0, b"\x00" * ao.ring)
        time.sleep(0.15)

    print("\n" + "=" * 88)
    print("复现性汇总：")
    for i, (hit, avg, lo, hi, r0) in enumerate(results, 1):
        print("  第%d次: 命中 %d/%d  平均增益 %+.1f dB (min %+.1f, max %+.1f)  ADC存活 %.0f"
              % (i, hit, len(freqs), avg, lo, hi, r0))
    hits = [r[0] for r in results]
    avgs = [r[1] for r in results]
    print("  命中数一致性: %s -> %s" % (hits, "★ 可复现" if max(hits) - min(hits) <= 1 else "⚠ 不稳定"))
    print("  增益波动: %.1f dB -> %s"
          % (max(avgs) - min(avgs),
             "★ 可复现" if max(avgs) - min(avgs) < 8 else "⚠ 不稳定"))

    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
