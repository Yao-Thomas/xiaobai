#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acoustic_check.py —— 用麦克风判断**喇叭到底有没有出声**

不依赖人的耳朵：先录静音基线，再边放音边录，比声学耦合。

  * 放音时电平明显高于基线 -> 喇叭在出声（那"听不到"就是别的原因）
  * 放音时电平和基线一样   -> 喇叭/功放没工作（硬件链路问题）

用法（要独占设备，先停服务）:
    sudo systemctl stop zynq-audio
    sudo python3 -u acoustic_check.py
    sudo systemctl start zynq-audio
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
TEST_F = 990.5


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
    print("=" * 80)
    print("声学自检：麦克风能不能听到喇叭")
    print("=" * 80)

    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    print("  codec: 0x1A=0x%02X 0x2E=%d 0x30=%d 0x27=0x%02X"
          % (ao.i2c.rd(0x1A), ao.i2c.rd(0x2E) & 0x3F,
             ao.i2c.rd(0x30) & 0x3F, ao.i2c.rd(0x27)))

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
    print("  I2S: TX=%d RX=%d   环=%d 字节"
          % (mem.rd(A.I2S_BASE, A.I2S_CORE_CTRL),
             mem.rd(A.I2S_RX_BASE, A.I2S_CORE_CTRL), cap.ring))

    frames = max(64, ao.period_bytes // 8)
    secs = 0.5
    silence = b"\x00" * ao.ring

    def grab():
        cap.cfg()
        d, _ = cap.grab(secs)
        return left_of(d)

    print()
    print("--- 1) 静音基线（不放音，连录 3 次）---")
    ao.buf.write(0, silence)
    time.sleep(0.5)
    bases = []
    for k in range(3):
        v = grab()
        R = rms(v)
        bases.append(R)
        print("    第%d次: RMS=%9.1f  峰值=%9d" % (k + 1, R,
              max(abs(x) for x in v) if v else 0))
        time.sleep(0.15)
    base = sum(bases) / len(bases)
    print("    基线平均 RMS = %.1f" % base)

    print()
    print("--- 2) 放音时采集（%.1f Hz，连放 3 次）---" % TEST_F)
    tones = []
    for k in range(3):
        tone = (make_sine(TEST_F, frames=frames, amp=0.6, pack=ao.pack) * 8)
        ao.buf.write(0, tone[:ao.ring])
        time.sleep(ao.ring / 352800.0 + 0.25)
        v = grab()
        R = rms(v)
        E = goe(v, TEST_F)
        tones.append((R, E))
        print("    第%d次: RMS=%9.1f  峰值=%9d  990Hz能量=%.3g"
              % (k + 1, R, max(abs(x) for x in v) if v else 0, E))
        time.sleep(0.15)

    ao.buf.write(0, silence)
    time.sleep(0.3)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    mR = sum(t[0] for t in tones) / len(tones)
    mE = sum(t[1] for t in tones) / len(tones)
    print()
    print("=" * 80)
    print("结论")
    print("=" * 80)
    print("  静音基线 RMS = %.1f" % base)
    print("  放音时   RMS = %.1f" % mR)
    if base > 0:
        gain = 20 * math.log10(max(1e-9, mR) / max(1e-9, base))
        print("  声学耦合增益 = %+.1f dB" % gain)
    else:
        gain = 999 if mR > 0 else 0
        print("  声学耦合增益 = (基线为 0)")

    print()
    if mR > base * 3 and mR > 50:
        print("  ★★ 麦克风**听到了**喇叭 —— 放音链路是通的，喇叭在出声。")
        print("     如果人耳听不到，检查：")
        print("       * 喇叭插头/排线是否接好（板子上的 SPK 座）")
        print("       * 是不是离板子太远、或环境太吵掩盖了")
        print("       * 音量听感（这次是 33 = 最大）")
    elif mR <= base * 1.5:
        print("  ✗✗ 麦克风**没听到**喇叭 —— 喇叭/功放确实没出声。")
        print("     数字侧寄存器全对，所以问题在模拟侧：")
        print("       * MD8002A 功放的供电（+5V）")
        print("       * 功放的 shutdown/enable 脚（可能有 GPIO 控制）")
        print("       * 喇叭本身的连接")
    else:
        print("  ⚠ 有一点耦合但不明显（介于两者之间）")
        print("     可能喇叭在出声但很小声，或者只是电气串扰")
    print()
    print("  990Hz 能量 = %.3g  （纯音回录应该远大于基线）" % mE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
