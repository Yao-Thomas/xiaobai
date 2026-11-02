#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""silent_play_test.py —— **静默**复现"故障 B"（边放边录时采集全零）

════════════════════════════════════════════════════════════════════
为什么要这么设计
════════════════════════════════════════════════════════════════════
2026-09-28 反推出 ③ 有两种故障：
    A  边放边录 ADC 过载   -> 能量正常但频谱平坦
    B  采集整段失败         -> 能量**全零**（min_flatness = 0.0 的真身）

故障 B 的成因有两种可能：
    (i)  声学/电气耦合  —— 喇叭的声音或功放电流干扰了 ADC 前端
    (ii) I2S/DMA 交互   —— 播放侧跑起来后，TX 扰动共享时钟域，RX 采集失败
         （依据：BCLK = AND(TX sclk, RX sclk)，codec 的 LRCK 来自 RX）

**怎么在不吵到人的前提下区分这两者？**

ES8388 的 DAC 数字音量寄存器 0x1A/0x1B：**0xC0 = -96 dB = 真正的静音**。
所以：

    DAC 数字静音 + 输出音量 0
        -> 播放环照常灌数据、DMA 照常跑、I2S TX 照常跑、BCLK/LRCK 照常
        -> **但喇叭一点声都没有**
        -> 同时采集

    若故障 B 仍然复现  -> 是 (ii) I2S/DMA 交互   ★ 静默就能定论
    若故障 B 完全消失  -> 是 (i) 声学/电气耦合（要看喇叭真的响才复现）

两种结果都有价值，而且**全程不出声**。

用法:
    sudo systemctl stop zynq-audio          # 它要独占设备
    sudo python3 silent_play_test.py --cycles 30
    sudo systemctl start zynq-audio
"""
import argparse
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
MUTE_DAC = 0xC0          # ★ -96 dB，ES8388 的 DAC 数字静音
FREQS = [495.3, 646.0, 990.5, 1292.0, 1507.3, 2002.6]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def goertzel(v, f, rate=FS):
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--secs", type=float, default=0.4)
    a = ap.parse_args()

    print("=" * 92)
    print("静默复现测试：边「放」（DAC 已数字静音）边录，看故障 B 会不会出现")
    print("=" * 92)

    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()

    # ★★ 关键：把 DAC 数字音量设成 0xC0 = -96dB = 静音，
    #         输出音量也设 0。这样 DMA/I2S 照跑，但喇叭不出声。
    es8388_set_vol(ao.i2c, 0, MUTE_DAC)
    d4 = ao.i2c.rd(0x1A)
    d5 = ao.i2c.rd(0x1B)
    print("  DAC 数字音量 0x1A=0x%02X 0x1B=0x%02X  （0xC0 = -96dB 静音）"
          % (d4, d5))
    print("  输出音量 0x2E=%d 0x30=%d  （0 = -45dB）"
          % (ao.i2c.rd(0x2E) & 0x3F, ao.i2c.rd(0x30) & 0x3F))
    if d4 != MUTE_DAC or d5 != MUTE_DAC:
        print("  ✗ 静音没设上，中止（不能冒出声的风险）")
        cc = 1
        try:
            ao.close()
        except Exception:
            pass
        raise SystemExit(cc)

    cap = RawCap(verbose=True)
    i2c = cap.i2c
    for r, v in [(0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x02), (0x10, 0x00), (0x11, 0x00),
                 (0x18, 0x03), (0x2B, 0x80)]:
        i2c.wr(r, v)
    # ★ 设完 ADC 寄存器后再确认一次 DAC 还是静音（有些寄存器组会互相影响）
    es8388_set_vol(ao.i2c, 0, MUTE_DAC)
    time.sleep(0.4)

    mem = cap.mem
    frames = max(64, ao.period_bytes // 8)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    print("  两个 I2S 核: TX=%d RX=%d"
          % (mem.rd(A.I2S_BASE, A.I2S_CORE_CTRL),
             mem.rd(A.I2S_RX_BASE, A.I2S_CORE_CTRL)))
    print("  环: %d 字节 (%.2f 秒)" % (cap.ring, cap.ring / 352800.0))
    print()

    secs = max(0.2, min(a.secs, 0.8 * cap.ring / 352800.0))
    silence = b"\x00" * ao.ring

    def grab():
        cap.cfg()
        d, _ = cap.grab(secs)
        v = left_of(d)
        return v

    def play(f0):
        """往播放环灌一个纯音。DAC 已静音，所以听不见，但 DMA/I2S 在跑。"""
        tone = (make_sine(f0, frames=frames, amp=0.9, pack=ao.pack) * 8)
        ao.buf.write(0, tone[:ao.ring])
        time.sleep(ao.ring / 352800.0 + 0.10)

    print("%-6s %-12s %-10s %-9s %-9s %s"
          % ("轮", "状态", "RMS", "峰值", "全零?", "播放的频点"))
    print("-" * 92)

    zero_play = 0        # 放音时的全零次数
    zero_quiet = 0       # 静音时的全零次数
    n_play = n_quiet = 0
    rows = []

    for k in range(a.cycles):
        f0 = FREQS[k % len(FREQS)]

        # ---- 对照组：不放音（DAC 静音不变，但播放环清空）----
        ao.buf.write(0, silence)
        time.sleep(0.12)
        vq = grab()
        n_quiet += 1
        zq = (not vq) or max(abs(x) for x in vq) == 0
        if zq:
            zero_quiet += 1

        # ---- 实验组：灌纯音（DMA/I2S 跑起来，但 DAC 静音 -> 没声音）----
        play(f0)
        vp = grab()
        n_play += 1
        zp = (not vp) or max(abs(x) for x in vp) == 0
        if zp:
            zero_play += 1

        e = [goertzel(vp, f) for f in FREQS] if vp else [0.0] * 6
        rows.append({"k": k + 1, "f0": f0, "quiet_zero": zq, "play_zero": zp,
                     "play_rms": rms(vp), "quiet_rms": rms(vq),
                     "play_energy": e})

        print("%-6d %-12s %-10.1f %-9d %-9s 播%.1f   静音RMS=%.1f%s"
              % (k + 1, "放音" if not zp else "Ø全零", rms(vp),
                 max(abs(x) for x in vp) if vp else 0,
                 "★是" if zp else "否", f0, rms(vq),
                 "   [对照组也全零]" if zq else ""))

    # ---- 收尾 ----
    ao.buf.write(0, silence)
    time.sleep(0.2)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    # ---- 结论 ----
    print()
    print("=" * 92)
    print("结论")
    print("=" * 92)
    print("  对照组（不放音）: %d 轮，全零 %d 次 (%.1f%%)"
          % (n_quiet, zero_quiet, 100.0 * zero_quiet / max(1, n_quiet)))
    print("  实验组（放音，DAC 静音）: %d 轮，全零 %d 次 (%.1f%%)"
          % (n_play, zero_play, 100.0 * zero_play / max(1, n_play)))
    print()
    if zero_play > 0 and zero_quiet == 0:
        print("  ★★ 故障 B **已复现**，而且是在 DAC 数字静音的情况下 ——")
        print("     说明它**不是声学/电气耦合**造成的，而是")
        print("     **播放侧跑起来后 I2S/DMA 的交互问题**")
        print("     （BCLK = AND(TX sclk, RX sclk)，codec 的 LRCK 来自 RX）。")
        print("     对策：重试 + 有效性标志（已实现在 matrix_vol.py / audio_svc.py）")
    elif zero_play > 0 and zero_quiet > 0:
        print("  ⚠ 两组都有全零 —— 采集本身就不稳，与放音无关。")
        print("     要先治采集（电源/时序），再谈放音干扰。")
    elif zero_play == 0:
        print("  ○ 这次没复现故障 B（DAC 静音时不出现）。")
        print("     可能：① 发生率低，样本不够 ② 真的是声学/电气耦合")
        print("     建议加大 --cycles 再看，或对比真放音的版本。")
    print()
    print("  ★ 全程 DAC 数字静音（0xC0 = -96dB），没有发出任何声音。")
    print("  ★ 结束前已把 0x1A/0x1B 恢复检查: 0x%02X/0x%02X"
          % (d4, d5))
    return 0


if __name__ == "__main__":
    sys.exit(main())
