#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成几个用来"听"的测试 WAV（16bit 立体声 44.1kHz，标准库即可）

    python make_test_wav.py  [输出目录]

生成：
    01_纯音_1kHz.wav     1kHz 正弦 5 秒
    02_左右声道.wav      先左声道 1 秒、再右声道 1 秒、再两边 1 秒
    03_小星星.wav        一听就知道对不对的旋律
    04_扫频.wav          100Hz -> 8kHz 扫频
"""
import math
import os
import struct
import sys
import wave

FS = 44100


def wav(path, frames):
    """frames: [(l, r)]，l/r 是 -1.0..1.0"""
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        buf = bytearray()
        for l, r in frames:
            buf += struct.pack("<hh",
                               int(max(-1.0, min(1.0, l)) * 32000),
                               int(max(-1.0, min(1.0, r)) * 32000))
        w.writeframes(bytes(buf))
    print("   %-28s %6.1f KB" % (os.path.basename(path),
                                 os.path.getsize(path) / 1024.0))


def sine(freq, sec, amp=0.4, left=True, right=True, fade=0.01):
    n = int(FS * sec)
    nf = max(1, int(FS * fade))
    out = []
    for i in range(n):
        v = amp * math.sin(2 * math.pi * freq * i / FS)
        # 头尾淡入淡出，免得"啪"一声
        if i < nf:
            v *= i / float(nf)
        if i > n - nf:
            v *= (n - i) / float(nf)
        out.append((v if left else 0.0, v if right else 0.0))
    return out


def silence(sec):
    return [(0.0, 0.0)] * int(FS * sec)


def tune(notes, beat=0.45, amp=0.35):
    """notes: [(频率 or None, 拍数)]"""
    out = []
    for f, b in notes:
        if f is None:
            out += silence(beat * b)
        else:
            # 简单包络，听起来像"叮"
            n = int(FS * beat * b)
            nf = max(1, int(FS * 0.02))
            for i in range(n):
                env = min(1.0, i / float(nf)) * math.exp(-2.2 * i / float(n))
                v = amp * env * math.sin(2 * math.pi * f * i / FS)
                # 加一点二次谐波，音色好听点
                v += 0.25 * amp * env * math.sin(4 * math.pi * f * i / FS)
                out.append((v, v))
    return out


def sweep(f0, f1, sec, amp=0.35):
    n = int(FS * sec)
    out = []
    ph = 0.0
    for i in range(n):
        t = i / float(n)
        f = f0 * (f1 / f0) ** t          # 对数扫频
        ph += 2 * math.pi * f / FS
        v = amp * math.sin(ph)
        nf = max(1, int(FS * 0.02))
        if i < nf:
            v *= i / float(nf)
        if i > n - nf:
            v *= (n - i) / float(nf)
        out.append((v, v))
    return out


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_testwav")
    os.makedirs(out, exist_ok=True)
    print("生成到", out)

    wav(os.path.join(out, "01_纯音_1kHz.wav"),
        silence(0.3) + sine(1000, 4.0) + silence(0.3))

    wav(os.path.join(out, "02_左右声道.wav"),
        silence(0.3)
        + sine(700, 1.2, left=True, right=False)      # 只有左耳
        + silence(0.25)
        + sine(700, 1.2, left=False, right=True)      # 只有右耳
        + silence(0.25)
        + sine(700, 1.5)                              # 两边
        + silence(0.3))

    C4, D4, E4, F4, G4, A4, C5 = (261.63, 293.66, 329.63, 349.23,
                                  392.00, 440.00, 523.25)
    twinkle = [(C4, 1), (C4, 1), (G4, 1), (G4, 1), (A4, 1), (A4, 1), (G4, 2),
               (F4, 1), (F4, 1), (E4, 1), (E4, 1), (D4, 1), (D4, 1), (C4, 2),
               None]
    twinkle = [n for n in twinkle if n is not None]
    wav(os.path.join(out, "03_小星星.wav"),
        silence(0.3) + tune(twinkle, beat=0.42) + silence(0.4))

    wav(os.path.join(out, "04_扫频.wav"),
        silence(0.3) + sweep(100, 8000, 6.0) + silence(0.3))


if __name__ == "__main__":
    main()
