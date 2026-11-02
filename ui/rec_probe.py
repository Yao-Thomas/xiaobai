#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_probe.py —— 录音链路探针

这一步要回答的核心问题：
    「开了 I2S 接收器之后，BCLK / codec 的 LRCK 到底活了没有？」

判据：S2MM 的 XFER_COUNT 在不在涨。
  * 涨  -> I2S 接收器在收数据 -> BCLK/LRC 一定在跑（之前就是这里死的）
  * 不涨 -> 时钟还是死的

顺便把 DDR 里的原始数据读出来做统计 + Goertzel 定点测频，
     判断 ADC 到底有没有把东西数字化进去。
"""
import math
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402


def goertzel(samples, fs, freq, n=None):
    """定点频率的能量（不需要 numpy）"""
    if n is None:
        n = len(samples)
    samples = samples[:n]
    if not samples:
        return 0.0
    w = 2.0 * math.pi * freq / fs
    c = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for x in samples:
        s0 = x + c * s1 - s2
        s2 = s1
        s1 = s0
    return math.sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) / len(samples)


def stats(name, vals):
    if not vals:
        print("   %-22s (空)" % name)
        return 0.0
    n = len(vals)
    mean = sum(vals) / float(n)
    peak = max(abs(v) for v in vals)
    rms = math.sqrt(sum(v * v for v in vals) / float(n))
    nz = sum(1 for v in vals if v != 0)
    print("   %-22s n=%d 均值=%.1f 峰值=%d RMS=%.1f 非零=%d(%.1f%%)"
          % (name, n, mean, peak, rms, nz, 100.0 * nz / n))
    return rms


def main():
    adc_in = sys.argv[1] if len(sys.argv) > 1 else "lin1"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

    a = A.AudioIn()
    try:
        print("=" * 70)
        print(" 录音探针  ADC输入=%s  录 %.1f 秒" % (adc_in, secs))
        print("=" * 70)
        a.codec_adc_up(adc_in)
        a.i2s_config()
        a.fmt_config()

        print("\n--- 启动录音，每 0.4 秒看一次 XFER_COUNT ---")
        a.start()
        last = 0
        t_end = time.time() + secs
        while time.time() < t_end:
            time.sleep(0.4)
            pos, tot = a.poll_pos()
            raw = a.raw_xfer()
            print("   XFER=%-8d 累计=%-8d (+%d)" % (raw, tot, tot - last))
            last = tot
        _, tot = a.poll_pos()
        dt = time.time() - a.t0
        rate = tot / dt if dt else 0
        print("\n>>> 共 %d 字节 / %.2f 秒 = %.1f B/s   期望 %d B/s"
              % (tot, dt, rate, A.FS * A.BYTES_PER_FRAME))
        if tot == 0:
            print(">>> !! XFER_COUNT 一点没动 —— BCLK/LRC 还是死的")
        else:
            print(">>> OK：I2S 接收器在收数据 => BCLK 和 codec 的 LRCK 是活的！")

        raw = a.read_ring()
        a.stop()

        print("\n--- 原始数据前 16 个 32bit 字")
        for i in range(0, min(64, len(raw)), 4):
            w = A.struct.unpack_from("<I", raw, i)[0]
            print("   [%3d] 0x%08X" % (i // 4, w))

        # 两种摆放都试：右对齐(低24位) / 左对齐(高24位)
        words = [A.struct.unpack_from("<I", raw, i)[0]
                 for i in range(0, len(raw) - 3, 4)]
        print("\n--- 两种摆放的解释对比")
        for tag, f in (("右对齐(低24位)", lambda w: ((w & 0xFFFFFF) ^ 0x800000)
                       - 0x800000),
                       ("左对齐(高24位)", lambda w: ((w >> 8) ^ 0x800000)
                        - 0x800000)):
            vals = [f(w) for w in words]
            rms = stats(tag, vals)
            if rms > 0:
                # 单声道取偶数下标（左声道）
                mono = vals[0::2]
                fs_mono = A.FS
                print("      定点测频(左声道): "
                      + "  ".join("%gHz=%.0f" % (fq, goertzel(mono, fs_mono, fq))
                                  for fq in (100, 500, 1000, 2000, 4000, 8000)))
    finally:
        a.close()


if __name__ == "__main__":
    main()
