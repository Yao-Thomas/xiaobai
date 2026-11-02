#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chime_proof.py —— 用**提示音**做一次极短的声学自证（③）

和之前用原始正弦/蜂鸣器的区别：
  * 信号是正常手机通知音（两声短铃，指数衰减），不刺耳
  * 每次只播 0.55 秒，最多 3 次（音量从低往高，**一成功就停**）

判据：提示音的两个音高是精确已知的
      E6 = 1318.51 Hz、A6 = 1760.00 Hz
      麦克风回录后，这两个频点的能量应该远高于 4 个对照频点。
      ratio = max(E@E6, E@A6) / median(E@对照频点)
      离线标定（test_audio_math.py）：纯音平坦度是 1e5 量级，白噪声只有 1.7。

用法: sudo systemctl stop zynq-audio; sudo python3 -u chime_proof.py
"""
import json
import math
import os
import struct
import sys
import time
import urllib.request
import wave

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402
from chime import make_chime, write_wav, RATE, E6, A6         # noqa: E402

FS = A.FS
NOTES = [E6, A6]
CTRL = [646.0, 990.5, 1507.3, 2002.6]
PROBE = NOTES + CTRL
VOLS = [10, 14, 18]          # 从低往高试，一成功就停
SECS = 1.20                  # 录一次覆盖一个提示音(0.55s)

CFG = {0x08: 0x00, 0x01: 0x50, 0x02: 0x00, 0x0B: 0x02,
       0x09: 0x66, 0x0A: 0x00, 0x10: 0x00, 0x11: 0x00,
       0x03: 0x51, 0x2B: 0x80,
       0x00: 0x06, 0x0C: 0x00, 0x0D: 0x02, 0x18: 0x03,
       0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8}


def left(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def win(v):
    n = len(v)
    if n < 8:
        return [float(x) for x in v]
    k = 2.0 * math.pi / (n - 1)
    return [v[i] * (0.5 - 0.5 * math.cos(k * i)) for i in range(n)]


def goe_multi(w, freqs, rate=FS):
    n = len(w)
    if n < 64:
        return [0.0 for _ in freqs]
    out = []
    for f in freqs:
        c = 2.0 * math.cos(2.0 * math.pi * f / rate)
        s1 = s2 = 0.0
        for x in w:
            s0 = x + c * s1 - s2
            s2, s1 = s1, s0
        out.append(math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (n / 4.0))
    return out


def main():
    # 提示音：先在板上生成 WAV（不出声）
    ch = make_chime("apple", amp=0.35)
    path = "/home/zynq/Music/提示音.wav"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_wav(ch, path)
    print("[0] 提示音已生成 %s  0.55 秒  峰值 %d"
          % (path, max(abs(x) for x in ch)), flush=True)

    cap = RawCap()
    # ★ 播放环形要放得下一整个提示音(0.55s)，否则会每 186ms 重复一次、更吵
    ao = AudioOut(period_bytes=32768, periods=16)
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, VOLS[0], 0)
    i2c = cap.i2c
    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    for r, v in CFG.items():
        i2c.wr(r, v)
    time.sleep(0.4)
    print("[0] 播放环形 = %d 字节 = %.2f 秒（够放一个提示音）"
          % (ao.ring, ao.ring / 352800.0), flush=True)

    # 把提示音铺在环形开头，其余填静音 -> 每环只响一次
    frames = ao.ring // 4
    pcm = bytearray()
    for i in range(frames):
        v = (ch[i] * 256) & 0xFFFFFF if i < len(ch) else 0
        pcm += struct.pack("<I", v)
    ring_chime = bytes(pcm)
    silence = b"\x00" * ao.ring

    def rec(secs=SECS):
        cap.cfg()
        cap.grab(0.08)
        cap.cfg()
        d, _ = cap.grab(secs)
        return left(d)

    def measure():
        """返回 (note_max, ctrl_med, 各频点能量, 静音RMS, 放音RMS)"""
        ao.buf.write(0, silence)
        time.sleep(ao.ring / 352800.0 + 0.12)
        rec()                                    # 丢暂态
        q = rec()
        e0 = goe_multi(win(q), PROBE)
        ctrl_med = sorted(e0[2:])[len(CTRL) // 2] or 1e-9
        note_max = max(e0[0], e0[1])
        return e0, note_max, ctrl_med, rms(q)

    ao.buf.write(0, silence)
    ao.start()
    time.sleep(0.3)

    e0, n0, c0, qrms = measure()
    print("\n[1] 静音基线: RMS=%.0f  E6=%.0f A6=%.0f  对照中位=%.0f"
          % (qrms, e0[0], e0[1], c0), flush=True)

    ok = False
    for k, vol in enumerate(VOLS):
        es8388_set_vol(ao.i2c, vol, 0)
        ao.buf.write(0, ring_chime)              # ← 从这里开始响
        time.sleep(0.12)
        t = rec()                                # 录到提示音
        ao.buf.write(0, silence)                 # ← 立刻停
        e = goe_multi(win(t), PROBE)
        ctrl_med = sorted(e[2:])[len(CTRL) // 2] or 1e-9
        note_max = max(e[0], e[1])
        ratio = note_max / ctrl_med
        base_ratio = n0 / c0
        print("\n[2.%d] 音量=%d  响了一声提示音" % (k + 1, vol), flush=True)
        print("      频点能量: E6=%.0f  A6=%.0f  | 对照 %s"
              % (e[0], e[1], " ".join("%.0f" % x for x in e[2:])), flush=True)
        print("      提示音峰/对照中位 = %.1f   (静音时是 %.1f)  RMS=%.0f"
              % (ratio, base_ratio, rms(t)), flush=True)
        if ratio > 10 * max(1.0, base_ratio):
            print("      ★ 麦克风确实收到了提示音", flush=True)
            ok = True
        if ok and k > 0:
            break
        if ok:
            # 再做两次，验证可复现（一共最多 3 次响声）
            for rep in range(2):
                ao.buf.write(0, ring_chime)
                time.sleep(0.12)
                t2 = rec()
                ao.buf.write(0, silence)
                e2 = goe_multi(win(t2), PROBE)
                cm = sorted(e2[2:])[len(CTRL) // 2] or 1e-9
                r2 = max(e2[0], e2[1]) / cm
                print("      [复现%d] 峰/对照 = %.1f  RMS=%.0f  E6=%.0f A6=%.0f"
                      % (rep + 1, r2, rms(t2), e2[0], e2[1]), flush=True)
            break

    ao.buf.write(0, silence)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()
    print("\n[3] 结论: %s" % ("★ 提示音回录自证成功（③ 达成）" if ok else
                            "⚠ 未检出，需换更高的音量或检查耦合"), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print("DONE(WITH ERROR)", flush=True)
