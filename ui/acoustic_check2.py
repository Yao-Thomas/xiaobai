#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acoustic_check2.py —— 用**正确的指标**判断喇叭有没有出声

上一个版本（acoustic_check.py）判据错了：它比"总 RMS"，
而这块板子的环境噪声 RMS 高达 5 万（低频主导），
放 990Hz 纯音时总 RMS 反而被压低 -> 误判成"没出声"。

正确指标：**只比 990Hz 处的能量**（Goertzel），
放音前后各测一次。纯音回录应该让这个值涨几个数量级。
"""
import math
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
F0 = 990.5
FREQS = [495.3, 646.0, 990.5, 1292.0, 1507.3, 2002.6]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def goe(v, f, rate=FS):
    n = len(v)
    if n < 64:
        return 0.0
    c = 2.0 * math.cos(2.0 * math.pi * f / rate)
    s1 = s2 = 0.0
    for i, x in enumerate(v):
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        s0 = x * w + c * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def main():
    print("=" * 84)
    print("声学自检 v2：比 **990Hz 处的能量**（不是总 RMS）")
    print("=" * 84)

    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()          # ★ 必须：配两个 I2S 核 + 分频
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    ao.start()               # ★★ 必须！开 DMA（CTRL_DMA_EN）+ 使能两个核
                             #    我之前漏了这句，所以测出来全是没有 DMA 的空转

    cap = RawCap(verbose=False)
    i2c = cap.i2c
    for r, v in [(0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x02), (0x10, 0x00), (0x11, 0x00),
                 (0x18, 0x03), (0x2B, 0x80)]:
        i2c.wr(r, v)
    time.sleep(0.4)

    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    frames = max(64, ao.period_bytes // 8)
    secs = 0.5
    silence = b"\x00" * ao.ring

    def grab():
        cap.cfg()
        d, _ = cap.grab(secs)
        return left_of(d)

    # ---- 基线：静音时的 990Hz 能量 ----
    print()
    print("--- 基线（不放音）---")
    ao.buf.write(0, silence)
    time.sleep(0.6)
    bE, bR = [], []
    for k in range(4):
        v = grab()
        bE.append(goe(v, F0))
        bR.append(rms(v))
        time.sleep(0.12)
    base_e = sum(bE) / len(bE)
    base_r = sum(bR) / len(bR)
    print("  990Hz 能量 = %.3g   总RMS = %.0f" % (base_e, base_r))

    # ---- 放音：990Hz 纯音 ----
    print()
    print("--- 放音（990.5Hz 纯音，amp 0.6，音量 33）---")
    pE, pR = [], []
    for k in range(4):
        tone = (make_sine(F0, frames=frames, amp=0.6, pack=ao.pack) * 8)
        ao.buf.write(0, tone[:ao.ring])
        time.sleep(ao.ring / 352800.0 + 0.25)
        v = grab()
        pE.append(goe(v, F0))
        pR.append(rms(v))
        print("    第%d次: 990Hz能量=%.3g  总RMS=%.0f" % (k + 1, pE[-1], pR[-1]))
        time.sleep(0.12)
    play_e = sum(pE) / len(pE)
    play_r = sum(pR) / len(pR)

    ao.buf.write(0, silence)
    time.sleep(0.3)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    print()
    print("=" * 84)
    print("结论")
    print("=" * 84)
    print("  %-14s %-16s %s" % ("", "990Hz 能量", "总 RMS"))
    print("  %-14s %-16.3g %.0f" % ("基线(不放音)", base_e, base_r))
    print("  %-14s %-16.3g %.0f" % ("放音(990Hz)", play_e, play_r))
    print()
    if base_e > 0:
        g = 10 * math.log10(max(1e-9, play_e) / max(1e-9, base_e))
        print("  990Hz 处能量提升 = %+.1f dB" % g)
    else:
        g = 999
        print("  990Hz 处能量提升 = (基线为 0)  放音值 %.3g" % play_e)

    print()
    if play_e > base_e * 10 and play_e > 1e12:
        print("  ★★ 喇叭**确实在出声** —— 990Hz 能量涨了 %.0f 倍。"
              % (play_e / max(1e-9, base_e)))
        print("     放音链路（DAC -> 功放 -> 喇叭 -> 空气 -> 麦克风）是通的。")
        print()
        print("     那么\"人耳听不到\"的原因只可能是：")
        print("       * 人不在板子旁边（远程网络访问时是听不到的）")
        print("       * 或者环境太吵、离得远")
        print("       * 或者喇叭音量在听感上确实偏小（硬件增益 2 倍的限制）")
    elif play_e > base_e * 3:
        print("  ○ 有一定提升（%.1f 倍），喇叭在出声但比较弱"
              % (play_e / max(1e-9, base_e)))
    else:
        print("  ✗ 990Hz 能量没有明显提升 —— 喇叭没出声。")
        print("    数字侧全对，所以查模拟侧：功放供电 / shutdown 脚 / 喇叭连接")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
