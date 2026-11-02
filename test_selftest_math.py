#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_selftest_math.py —— 离线验证声学自测的数学部分（不需要板子）

板子不在的时候，先把算法验对。测三件事：

  ① Goertzel 单频检测准不准
     - 有纯音时该频率能量应该远大于没有的时候
     - 换别的频率去测同一个信号，能量应该很低

  ② play/base 比值判据合不合理
     - 造一个"放音时目标频率涨了 20dB"的信号 -> 应该判"优秀"
     - 造一个"只有工频谐波、目标频率没涨"的信号 -> 应该判"失败"
       ★ 这正是文档里踩过的坑：找最大能量会找到 100Hz

  ③ 24 位符号扩展对不对
     - 字节 FE FF FF 00 应该解成 -2，不是 16777214 也不是 65535

用法:
    python test_selftest_math.py
"""
import array
import math
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RATE = 44100


def goertzel(samples, freq, rate=RATE):
    n = len(samples)
    if n == 0:
        return 0.0
    k = int(0.5 + n * freq / rate)
    w = 2.0 * math.pi * k / n
    coeff = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return (s1 * s1 + s2 * s2 - coeff * s1 * s2) / (n * n)


def gen(freq, n, amp, noise=0.0, hum=0.0, seed=1):
    """合成一段信号：目标纯音 + 白噪声 + 工频谐波"""
    random.seed(seed)
    out = []
    for i in range(n):
        v = amp * math.sin(2 * math.pi * freq * i / RATE)
        if hum:
            v += hum * math.sin(2 * math.pi * 100 * i / RATE)     # 100Hz 工频
            v += hum * 0.6 * math.sin(2 * math.pi * 200 * i / RATE)
        if noise:
            v += random.gauss(0, noise)
        out.append(int(max(-8388608, min(8388607, v))))
    return out


def db(x):
    return 10 * math.log10(x) if x > 0 else -999.0


def main():
    n = int(1.2 * RATE)
    F = 990.53
    ok = True

    print("=" * 74)
    print(" 离线验证声学自测的数学部分")
    print("=" * 74)

    # ---------- ① Goertzel ----------
    print("\n【①】Goertzel 单频检测")
    tone = gen(F, n, 2000000)                      # 只有目标纯音
    silence = gen(F, n, 0, noise=100)

    e_tone = goertzel(tone, F)
    e_sil = goertzel(silence, F)
    e_other = goertzel(tone, 2000)                 # 拿别的频率去测这个纯音

    print("   目标频率 F=%.2f Hz, n=%d" % (F, n))
    print("   纯音时 F 的能量      = %.3e" % e_tone)
    print("   静音时 F 的能量      = %.3e" % e_sil)
    print("   纯音时用 2000Hz 测   = %.3e" % e_other)
    r1 = db(e_tone) - db(e_other)
    print("   目标 / 非目标 = %.1f dB" % r1)
    if r1 > 30:
        print("   ✓ 频率选择性好（>30dB）")
    else:
        print("   ✗ 频率选择性不足")
        ok = False

    # ---------- ② 比值判据 ----------
    print("\n【②】play/base 比值判据")

    # 场景 A：麦克风真的听到了（放音时目标频率涨了约 20dB）
    base_a = gen(0, n, 0, noise=200, hum=80000)
    play_a = gen(F, n, 800000, noise=200, hum=80000)
    ra = db(goertzel(play_a, F)) - db(goertzel(base_a, F))
    print("   场景A（真听到）: 比值 %.1f dB" % ra)
    if ra >= 12:
        print("      -> 判【优秀】 ✓")
    else:
        print("      -> 期望≥12dB，实际 %.1f，判据有问题 ✗" % ra)
        ok = False

    # 场景 B：★ 只有工频谐波，目标频率没涨（文档里踩过的坑）
    base_b = gen(0, n, 0, noise=200, hum=2000000)
    play_b = gen(0, n, 0, noise=200, hum=2000000)   # 目标频率完全没有
    rb = db(goertzel(play_b, F)) - db(goertzel(base_b, F))
    hum_energy = db(goertzel(base_b, 100))
    tgt_energy = db(goertzel(base_b, F))
    print("   场景B（只有工频）: 比值 %.1f dB" % rb)
    print("      100Hz 能量 %.1f dB  vs  目标频率能量 %.1f dB"
          % (hum_energy, tgt_energy))
    print("      ★ 100Hz 比目标高 %.1f dB —— 如果按『找最大能量』就会误判成 100Hz"
          % (hum_energy - tgt_energy))
    if rb < 6:
        print("      -> 判【失败】 ✓ （比值判据没被骗）")
    else:
        print("      -> 期望<6dB，实际 %.1f，判据被工频骗了 ✗" % rb)
        ok = False

    # ---------- ③ 24 位符号扩展 ----------
    print("\n【③】24 位数据符号扩展")
    cases = [
        (b"\xFE\xFF\xFF\x00", -2, "0xFFFFFE = -2"),
        (b"\x00\x00\x00\x00", 0, "0"),
        (b"\xFF\xFF\x7F\x00", 8388607, "最大正数"),
        (b"\x00\x00\x80\x00", -8388608, "最小负数"),
        (b"\x01\x00\x00\x00", 1, "1"),
    ]
    import struct
    for raw, want, desc in cases:
        v = struct.unpack("<i", raw)[0]
        if v >= 0x800000:
            v -= 0x1000000
        status = "✓" if v == want else "✗"
        print("   %s  %s -> %-12d (期望 %-12d)  %s"
              % (status, raw.hex(), v, want, desc))
        if v != want:
            ok = False

    # 顺便验证"错误做法"会得到什么
    raw = b"\xFE\xFF\xFF\x00"
    v32 = struct.unpack("<i", raw)[0]
    print("\n   对比错误做法（同一个字节）：")
    print("     直接当 int32      -> %d   （假的大正数）" % v32)
    print("     右移 8 位         -> %d   （另一个假象，会被削顶成 32767）"
          % (v32 >> 8))
    print("     从 bit23 符号扩展 -> %d   ✓ 正确" %
          (v32 - 0x1000000 if v32 >= 0x800000 else v32))

    print()
    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面标 ✗ 的"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
