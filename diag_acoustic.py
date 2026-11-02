#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_acoustic.py —— 查声学自测那个"音量越大信号越小"的怪现象

════════════════════════════════════════════════════════════════════
现象（实测记录）
════════════════════════════════════════════════════════════════════
    vol=40  → 放音峰值 32767，比值 +25.3 dB
    vol=70  → 放音峰值   851，比值 +12.1 dB   ← 音量调大了，信号反而小了？
    vol=100 → 放音峰值   964，比值  +5.3 dB
    vol=140 → 放音峰值 65535，比值 +12.0 dB

两个可能：
    A. 【不稳定】—— 放音本身时好时坏（aplay 有时候没放出来）
    B. 【音量映射反了】—— ES8388 的数字音量寄存器可能是反的

这个脚本分开验这两件事：
    ① 同一个音量连测 6 次 —— 看方差
    ② 音量从 0 扫到 192 —— 看峰值/比值是不是单调的
    ③ 顺便看 amixer 报的 dB 值对不对

用法（板上 root）:
    sudo python3 diag_acoustic.py
    sudo python3 diag_acoustic.py --repeat 10
"""
import argparse
import array
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, "/home/zynq")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CAP_DEV = "hw:0,1"
PLAY_DEV = "default"
RATE = 44100
FREQ = 990.53

# 静音锁：这个诊断要放音，必须显式同意
if os.path.exists("/etc/zynq-silent") and "--force" not in sys.argv:
    sys.exit("静音锁开着。要跑这个诊断请加 --force（表示用户已同意放音）")


def goertzel(samples, freq, rate=RATE):
    """算某个频率的能量（Goertzel，比 FFT 省）"""
    n = len(samples)
    if n == 0:
        return 0.0
    k = int(0.5 + n * freq / rate)
    w = 2.0 * math.pi * k / n
    cw, sw = math.cos(w), math.sin(w)
    coeff = 2.0 * cw
    s0 = s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(s1 * s1 + s2 * s2 - coeff * s1 * s2) / n


def set_vol(v):
    subprocess.run(["amixer", "-q", "-c", "0", "sset", "Playback", str(v)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_vol():
    try:
        p = subprocess.run(["amixer", "-c", "0", "sget", "Playback"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        import re
        m = re.search(r"\[(\d+)%\]\s*\[(-?[\d.]+)dB\]",
                      p.stdout.decode("utf-8", "replace"))
        if m:
            return int(m.group(1)), float(m.group(2))
    except Exception:
        pass
    return None, None


def capture(secs=1.0):
    dur = int(math.ceil(secs))
    p = subprocess.run(
        ["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE", "-c", "2",
         "-r", str(RATE), "-d", str(dur), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=dur + 15)
    raw = p.stdout[:int(secs * RATE) * 8]
    a = array.array("i")
    a.frombytes(raw[:len(raw) & ~3])
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    return a[0::2]          # 左声道


def tone_wav(freq, secs, path="/tmp/_diag_tone.wav"):
    import struct
    n = int(secs * RATE)
    peak = int(0.6 * 32767)
    buf = array.array("h")
    for i in range(n):
        v = int(peak * math.sin(2 * math.pi * freq * i / RATE))
        buf.append(v)
        buf.append(v)
    with open(path, "wb") as f:
        d = buf.tobytes()
        f.write(b"RIFF" + struct.pack("<I", 36 + len(d)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, RATE,
                                      RATE * 4, 4, 16))
        f.write(b"data" + struct.pack("<I", len(d)))
        f.write(d)
    return path


def one(vol, secs=1.2, wav=None):
    """放一次 + 录一次，返回 (峰值, 目标频率能量, 比值dB)"""
    set_vol(vol)
    time.sleep(0.15)
    # 基线
    base = capture(secs)
    b_tone = goertzel(base, FREQ)
    # 边放边录
    p = subprocess.Popen(["aplay", "-q", "-D", PLAY_DEV, wav],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.2)
    play = capture(secs)
    try:
        p.wait(timeout=secs + 5)
    except Exception:
        p.kill()
    p_tone = goertzel(play, FREQ)
    pk = max(abs(x) for x in play) if play else 0
    ratio = (p_tone / b_tone) if b_tone > 0 else 0.0
    db = 20 * math.log10(ratio) if ratio > 0 else -999
    return pk, p_tone, db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=6)
    ap.add_argument("--secs", type=float, default=1.2)
    ap.add_argument("--vol", type=int, default=80)
    # ★ 静音锁开着的时候要跑这个诊断，必须显式表态。
    #   上面用 sys.argv 检查过了，但 argparse 也要认识这个参数，
    #   否则会报 "unrecognized arguments: --force"（踩过）。
    ap.add_argument("--force", action="store_true",
                    help="静音锁开着也放音（表示用户已明确同意）")
    a = ap.parse_args()

    print("=" * 78)
    print(" 声学自测异常诊断")
    print("=" * 78)
    wav = tone_wav(FREQ, a.secs)
    print(" 测试音：%s（%.1f Hz，%.1f 秒）" % (wav, FREQ, a.secs))
    print()

    # ═════════════════════════════════ ① 重复性
    print("① 同一个音量（%d）连测 %d 次 —— 看稳不稳" % (a.vol, a.repeat))
    print("   %-6s %-12s %-14s %s" % ("次数", "放音峰值", "目标频率能量", "比值dB"))
    pks, dbs = [], []
    for i in range(a.repeat):
        pk, tone, db = one(a.vol, a.secs, wav)
        pks.append(pk)
        dbs.append(db)
        print("   %-6d %-12d %-14.1f %.1f" % (i + 1, pk, tone, db))
    print()
    if len(dbs) > 1:
        mu = sum(dbs) / len(dbs)
        var = sum((x - mu) ** 2 for x in dbs) / len(dbs)
        sd = math.sqrt(var)
        print("   均值 %.1f dB   标准差 %.1f dB   最小 %.1f   最大 %.1f"
              % (mu, sd, min(dbs), max(dbs)))
        if sd > 6:
            print("   ★★ 方差很大 —— 放音/录音【不稳定】，不是音量映射的问题")
        else:
            print("   ✓ 比较稳定")
    print()

    # ═════════════════════════════════ ② 音量曲线
    print("② 音量从 0 扫到 192 —— 看单调不单调")
    print("   %-6s %-10s %-12s %-14s %s"
          % ("设置", "amixer%", "dB", "放音峰值", "比值dB"))
    prev_pk = None
    mono_ok = True
    for v in (0, 20, 40, 60, 80, 100, 120, 140, 160, 180, 192):
        pct, db_rep = get_vol() if v == 0 else (None, None)
        pk, tone, db = one(v, a.secs, wav)
        pct, db_rep = get_vol()
        print("   %-6d %-10s %-12s %-14d %.1f"
              % (v, pct, db_rep, pk, db))
        if prev_pk is not None and v > 0 and pk < prev_pk * 0.5:
            mono_ok = False
        prev_pk = pk
    print()
    if mono_ok:
        print("   ✓ 峰值随音量大致单调")
    else:
        print("   ★★ 峰值不单调 —— 音量映射可能有问题（ES8388 的数字音量寄存器"
              "常常是反的：0 = 0dB 最大）")
    print()

    # ═════════════════════════════════ ③ 恢复
    set_vol(140)
    print("③ 已把音量恢复成 140")
    print()
    print("=" * 78)
    print(" 判读")
    print("=" * 78)
    print(" ★ 如果①方差大 → 先解决『放音不稳』（可能是 aplay 和设备占用冲突）")
    print(" ★ 如果①稳、②不单调 → 是音量映射问题，改 amixer 的用法或直接写寄存器")
    print(" ★ 如果①稳、②单调 → 那之前看到的波动是偶发，加个重试就行")


if __name__ == "__main__":
    main()
