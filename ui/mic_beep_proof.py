#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦克风是否真的"听得见"—— 用板载无源蜂鸣器当声源，全自动、免耳朵。

板子上的蜂鸣器 (gpio0_tri_io[4] = M14) 和麦克风在同一块 PCB 上，
哔哔响一定能被麦克风拾取。对比"静音"和"蜂鸣"两段录音即可判定。

用法: sudo python3 mic_beep_proof.py
"""
import sys
import io
import json
import time
import math
import wave
import struct
import threading
import urllib.request

sys.path.insert(0, "/home/zynq/ui")
from beep import open_beeper, beep                          # noqa: E402

SVC = "http://127.0.0.1:8767"


def rec(secs, rate=22050):
    body = json.dumps({"secs": secs, "rate": rate, "mono": True}).encode()
    req = urllib.request.Request(SVC + "/record", data=body,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=120).read()


def samples(wav_bytes):
    w = wave.open(io.BytesIO(wav_bytes), "rb")
    rate = w.getframerate()
    raw = w.readframes(w.getnframes())
    return list(struct.unpack("<%dh" % (len(raw) // 2), raw)), rate


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def goe(v, f, rate):
    if len(v) < 64:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in v:
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (len(v) / 2.0)


def peakf(v, rate, lo=800, hi=6000, step=100):
    best, bf = -1.0, 0
    f = lo
    while f <= hi:
        g = goe(v, f, rate)
        if g > best:
            best, bf = g, f
        f += step
    return bf, best


def main():
    fd = open_beeper()
    if fd is None:
        print("找不到蜂鸣器设备")
        return
    print("[proof] 蜂鸣器已打开")

    # 1) 静音基准
    time.sleep(0.3)
    a, rate = samples(rec(2.0))
    ra = rms(a)

    # 2) 边哔边录（后台线程哔）
    stop = {"v": False}

    def noise():
        n = 0
        while not stop["v"] and n < 40:
            try:
                beep(1, 90, fd=fd, gap=0.0)
            except Exception:
                break
            n += 1
            time.sleep(0.02)

    th = threading.Thread(target=noise)
    th.start()
    time.sleep(0.15)
    b, rate = samples(rec(2.0))
    stop["v"] = True
    th.join()
    rb = rms(b)

    print("\n采样率 %d Hz, 每段 %d 个样本" % (rate, len(a)))
    print("%-14s %12s %12s %10s" % ("条件", "RMS", "峰值", "800-6k峰"))
    for tag, v in (("静音", a), ("蜂鸣", b)):
        pf, pg = peakf(v, rate)
        print("%-14s %12.1f %12d %6dHz(%.0f)"
              % (tag, rms(v), max(abs(x) for x in v), pf, pg))
    db = 20 * math.log10(max(1e-9, rb) / max(1e-9, ra))
    print("\nRMS 蜂鸣/静音 = %.2fx (%+.1f dB)" % (rb / max(1e-9, ra), db))
    # 蜂鸣器典型 2~4kHz，看这一段单独的能量
    gb = sum(goe(b, f, rate) for f in range(2000, 4201, 100))
    ga = sum(goe(a, f, rate) for f in range(2000, 4201, 100))
    print("2-4kHz 能量 蜂鸣/静音 = %.2fx" % (gb / max(1e-9, ga)))
    if db > 3.0 or gb > 1.5 * ga:
        print("★ 麦克风确实拾取到了板载蜂鸣器的声音 —— 模拟录音通路可用")
    else:
        print("⚠ 没拾取到 —— 麦克风偏置或输入通道可能还需要确认")
    try:
        fd.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
