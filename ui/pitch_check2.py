#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pitch_check2.py —— 找**纯音到底去了哪个频率**

上一版错在"找能量最大的频率"—— 结果找到 100 Hz 的**市电工频谐波**
（基线在 100 Hz 就有 1.97e17，而纯音提升只有 +0.5 dB）。

正确做法：对每个频点算 **play/base 的比值**，比值最大的那才是纯音。

顺便把原始数据落盘，方便事后复核。
"""
import json
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
PLAY_F = 1000.0


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
    print("音高实测 v2：按 play/base **比值**找纯音（不找能量最大）")
    print("=" * 84)

    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    ao.start()

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
    ring = ao.ring
    silence = b"\x00" * ring

    def cap1(secs=0.6):
        cap.cfg()
        d, _ = cap.grab(secs)
        return left_of(d)

    print("  采基线...")
    ao.buf.write(0, silence)
    time.sleep(0.5)
    base = cap1()

    print("  放 %.0f Hz 并采...（会出声）" % PLAY_F)
    tone = (make_sine(PLAY_F, frames=frames, amp=0.9, pack=ao.pack) * 8)
    ao.buf.write(0, tone[:ring])
    time.sleep(0.35)
    play = cap1()

    ao.buf.write(0, silence)
    time.sleep(0.25)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    if not play or not base:
        print("  没采到数据")
        return 1

    # ---- 扫频，算比值 ----
    freqs = []
    f = 40.0
    while f < 4000:
        freqs.append(f)
        f *= 1.02
    print("  扫描 %d 个频点（40~4000 Hz）..." % len(freqs))

    rows = []
    for f in freqs:
        eb = goe(base, f)
        ep = goe(play, f)
        ratio = ep / eb if eb > 0 else (1e9 if ep > 0 else 1.0)
        rows.append((f, eb, ep, ratio))

    rows.sort(key=lambda r: -r[3])
    print()
    print("  按「放音/基线」比值排序的前 12 名：")
    print("    %-10s %-14s %-14s %-10s %s"
          % ("频率Hz", "基线能量", "放音能量", "比值", "提升dB"))
    print("    " + "-" * 70)
    for f, eb, ep, ra in rows[:12]:
        db = 10 * math.log10(max(1e-9, ra)) if ra > 0 else 0
        print("    %-10.1f %-14.3g %-14.3g %-10.2f %+.1f" % (f, eb, ep, ra, db))

    top_f, _, _, top_r = rows[0]
    print()
    print("  ★ 提升最大的频点 = %.1f Hz  (比值 %.2f = %+.1f dB)"
          % (top_f, top_r, 10 * math.log10(max(1e-9, top_r))))
    print("    我放的是 %.1f Hz" % PLAY_F)
    if abs(top_f - PLAY_F) / PLAY_F < 0.2:
        print("    => **音高正确**，放音速率没问题")
    else:
        print("    => 音高是标称的 %.3f 倍" % (top_f / PLAY_F))
        if top_f < PLAY_F:
            print("       => 放慢了 %.1f 倍" % (PLAY_F / top_f))
        else:
            print("       => 放快了 %.1f 倍" % (top_f / PLAY_F))

    # 落盘
    with open("/tmp/pitch_check2.json", "w") as fp:
        json.dump({"play_f": PLAY_F,
                   "top": [r[0] for r in rows[:40]],
                   "rows": [[r[0], r[1], r[2], r[3]] for r in rows[:200]]},
                  fp)
    print()
    print("  明细已存 /tmp/pitch_check2.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
