#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_spectrum.py —— 看采集到的音频到底有哪些频率（纯 Python FFT）

干什么：
    录一段 -> FFT -> 列出能量最高的若干频点 -> 判断"喇叭有没有真的出声"

为什么需要：
    声学自测如果只报"990Hz 比值 1.1dB"，看不出到底是
      · 喇叭没响
      · 还是响了但麦克风听不到
      · 还是环境噪声太大把它淹了
    把频谱打出来，一眼就能分清。

用法:
    sudo python3 audio_spectrum.py              # 录 2 秒看频谱
    sudo python3 audio_spectrum.py --secs 3
    sudo python3 audio_spectrum.py --play 990   # 放 990Hz 的同时录
"""
import argparse
import array
import math
import os
import struct
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RATE = 44100


def fft(re, im):
    """原地 radix-2 FFT（和 waveform_ai.py 同一份实现）"""
    n = len(re)
    if n & (n - 1):
        raise ValueError("长度必须是 2 的幂")
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wr, wi = math.cos(ang), math.sin(ang)
        half = length >> 1
        for i in range(0, n, length):
            cr, ci = 1.0, 0.0
            for k in range(i, i + half):
                ur, ui = re[k], im[k]
                vr = re[k + half] * cr - im[k + half] * ci
                vi = re[k + half] * ci + im[k + half] * cr
                re[k], re[k + half] = ur + vr, ur - vr
                im[k], im[k + half] = ui + vi, ui - vi
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1


def capture(secs):
    """录一段，返回单声道样本（左声道，已符号扩展）"""
    dur = int(math.ceil(secs))
    p = subprocess.run(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-c", "2",
         "-r", str(RATE), "-d", str(dur), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=dur + 15)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace")[:150])
    raw = p.stdout[:int(secs * RATE) * 8]
    a = array.array("i")
    a.frombytes(raw[:len(raw) & ~3])
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    return a[0::2]


def play_tone(freq, secs, vol=50):
    subprocess.run(["amixer", "-q", "-c", "0", "sset", "Playback", str(vol)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n = int(secs * RATE)
    peak = int(0.6 * 32767)
    buf = array.array("h")
    for i in range(n):
        v = int(peak * math.sin(2 * math.pi * freq * i / RATE))
        buf.append(v)
        buf.append(v)
    wav = "/tmp/_spec_tone.wav"
    with open(wav, "wb") as f:
        data = buf.tobytes()
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, RATE,
                                      RATE * 4, 4, 16))
        f.write(b"data" + struct.pack("<I", len(data)))
        f.write(data)
    return subprocess.Popen(["aplay", "-q", "-D", "hw:0,1", wav],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def spectrum(samples, nfft=8192):
    """对整段做 FFT（取前 nfft 点，加 Hann 窗），返回 [(freq, mag_db), ...]"""
    n = min(nfft, len(samples))
    if n < 256:
        return []
    # 把这段的均值去掉（去直流）
    seg = samples[:n]
    mean = sum(seg) / n
    re = [0.0] * n
    im = [0.0] * n
    for i in range(n):
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        re[i] = (seg[i] - mean) * w
    fft(re, im)
    out = []
    for k in range(1, n // 2):
        m = math.sqrt(re[k] * re[k] + im[k] * im[k]) / (n / 2.0)
        db = 20 * math.log10(m / 8388608.0) if m > 0 else -999.0
        out.append((k * RATE / float(n), db))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=2.0)
    ap.add_argument("--play", type=float, default=0, help="同时放这个频率")
    ap.add_argument("--vol", type=int, default=50)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("需要 root")

    print("=" * 76)
    print(" 音频频谱分析（看麦克风到底听到了什么）")
    print("=" * 76)

    if a.play:
        print("\n★ 同时放 %.1f Hz（音量 %d）" % (a.play, a.vol))
        pp = play_tone(a.play, a.secs, a.vol)
        time.sleep(0.3)
    else:
        pp = None

    print(" 录音 %.1f 秒…" % a.secs)
    samples = capture(a.secs)
    if pp:
        try:
            pp.wait(timeout=a.secs + 5)
        except Exception:
            pp.kill()

    if not samples:
        print(" ★ 没录到东西")
        return 1

    rms = math.sqrt(sum(float(x) * x for x in samples) / len(samples))
    print(" 样本 %d   RMS = %.1f dBFS   峰值 = %d"
          % (len(samples), 20 * math.log10(rms / 8388608.0) if rms > 0 else -999,
             max(abs(x) for x in samples)))

    sp = spectrum(samples)
    if not sp:
        print(" ★ 频谱太短")
        return 1

    # 按能量排序，列前 N 个
    top = sorted(sp, key=lambda x: -x[1])[:a.top]
    print("\n 能量最高的 %d 个频点:" % a.top)
    print("   %-10s %-10s %s" % ("频率(Hz)", "电平(dBFS)", "相对峰值"))
    peak_db = top[0][1] if top else -999
    for f, db in top:
        bar = "#" * max(0, int((db - peak_db + 60) / 3))
        print("   %-10.1f %-10.1f %s" % (f, db, bar))

    # 如果指定了放音频率，单独看那个点
    if a.play:
        near = [x for x in sp if abs(x[0] - a.play) < RATE / 8192.0 * 1.5]
        if near:
            f0, db0 = max(near, key=lambda x: x[1])
            # 找它附近的背景（±200Hz 但排除它自己）
            bg = [db for f, db in sp
                  if 50 < abs(f - a.play) < 500]
            bg_avg = sum(bg) / len(bg) if bg else -999
            print("\n ★ 目标频率 %.1f Hz 处: %.1f dBFS" % (f0, db0))
            print("   邻近背景(±50~500Hz)均值: %.1f dBFS" % bg_avg)
            print("   ⇒ 信噪比 %.1f dB" % (db0 - bg_avg))
            if db0 - bg_avg > 6:
                print("   ★★★ 听到了！（信噪比 > 6dB）")
            elif db0 - bg_avg > 3:
                print("   ★ 有一点点（可能是窜扰）")
            else:
                print("   ★ 没听到 —— 喇叭可能没出声，或麦克风听不到")

    # 顺便看看低频有没有工频
    hum = [x for x in sp if x[0] < 300]
    if hum:
        hf, hdb = max(hum, key=lambda x: x[1])
        print("\n 低频段最强: %.1f Hz @ %.1f dBFS（工频/机械噪声常见位置）"
              % (hf, hdb))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
