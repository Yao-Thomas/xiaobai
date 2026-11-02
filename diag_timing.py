#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_timing.py —— 查放音"时好时坏"是不是采集窗口没对上

═══ 前面的结论 ═══
    zynq-audio 服务开着 vs 停掉，两组都不稳（都只有 1~2/6 成功）
    aplay 返回码全是 0（它认为放完了）
    ⇒ 不是服务占用冲突

═══ 这个脚本验的假设 ═══
    可能是【采集窗口没对上】：
      · arecord 启动有延迟（打开设备 + 装参数可能要几百毫秒）
      · aplay 放 1 秒的音，如果 arecord 300ms 后才真正开始录，
        而 aplay 已经放到一半甚至放完了 —— 那就什么都录不到
      · 但如果音长 4 秒，采集窗口怎么都该覆盖到

    如果长音每次都成功 → 那之前的不稳定是【测量方法】的问题，不是硬件
    如果长音也时好时坏   → 那才是 I2S/DMA 层的真问题

用法（板上 root）:
    sudo python3 diag_timing.py
    sudo python3 diag_timing.py --force
"""
import argparse
import array
import math
import os
import struct
import subprocess
import sys
import time

RATE = 44100
FREQ = 990.53
CAP_DEV = "hw:0,1"
PLAY_DEV = "default"

if os.path.exists("/etc/zynq-silent") and "--force" not in sys.argv:
    sys.exit("静音锁开着。加 --force 表示用户已同意")


def tone(freq, secs, path):
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


def rms_and_peak(path):
    a = array.array("i")
    a.frombytes(open(path, "rb").read())
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    L = a[0::2]
    if not L:
        return 0.0, 0
    rms = math.sqrt(sum(float(x) * x for x in L) / len(L))
    return rms, max(abs(x) for x in L)


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
        s2, s1 = s1, s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - coeff * s1 * s2)) / n


def tone_energy(path):
    a = array.array("i")
    a.frombytes(open(path, "rb").read())
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    return goertzel(a[0::2], FREQ)


def measure_startup(cmd, out_path):
    """量一条命令从启动到真正开始产出数据要多久"""
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    first = None
    total = 0
    with open(out_path, "wb") as f:
        while True:
            c = p.stdout.read(4096)
            if not c:
                break
            if first is None:
                first = time.time() - t0
            total += len(c)
            f.write(c)
    p.wait()
    return (first if first is not None else -1), (time.time() - t0), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--secs", type=float, default=4.0)
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()

    print("=" * 78)
    print(" 放音/采集 时序诊断")
    print("=" * 78)

    wav = tone(FREQ, a.secs, "/tmp/_tim_tone.wav")
    print(" 测试音: %.1f Hz, %.1f 秒 -> %s" % (FREQ, a.secs, wav))
    print()

    # ══════════════════════════════ ① 量启动延迟
    print("① 量启动延迟")
    print("   （如果 arecord 要几百毫秒才出数据，短音的采集窗口就废了）")
    for name, cmd, out in (
            ("arecord 1秒", ["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE",
                             "-c", "2", "-r", str(RATE), "-d", "1",
                             "-t", "raw"], "/tmp/_tim_arec.raw"),
            ("aplay 空跑", ["aplay", "-q", "-D", PLAY_DEV, wav], "/tmp/_tim_apl.out")):
        first, total_t, nbytes = measure_startup(cmd, out)
        print("   %-12s 首个数据 %.0f ms   总共 %.2f 秒   %d 字节"
              % (name, first * 1000, total_t, nbytes))
    print()

    # ══════════════════════════════ ② 长音 x N 次
    print("② ★ 长音（%.1f 秒）连测 %d 次 —— 采集窗口一定覆盖得住"
          % (a.secs, a.reps))
    print("   %-5s %-14s %-14s %-12s %s"
          % ("次数", "基线能量", "放音能量", "峰值", "比值dB"))
    hits = 0
    for i in range(a.reps):
        # 基线
        subprocess.run(["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE",
                        "-c", "2", "-r", str(RATE), "-d", "2",
                        "-t", "raw"],
                       stdout=open("/tmp/_tim_b.raw", "wb"),
                       stderr=subprocess.DEVNULL)
        # 边放边录：先起 aplay，等 0.3 秒（让它真正开始出声），再录
        p = subprocess.Popen(["aplay", "-q", "-D", PLAY_DEV, wav],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        subprocess.run(["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE",
                        "-c", "2", "-r", str(RATE), "-d", "2",
                        "-t", "raw"],
                       stdout=open("/tmp/_tim_p.raw", "wb"),
                       stderr=subprocess.DEVNULL)
        try:
            p.wait(timeout=a.secs + 5)
        except Exception:
            p.kill()

        b_e = tone_energy("/tmp/_tim_b.raw")
        p_e = tone_energy("/tmp/_tim_p.raw")
        _, pk = rms_and_peak("/tmp/_tim_p.raw")
        ratio = (p_e / b_e) if b_e > 0 else 0.0
        db = 20 * math.log10(ratio) if ratio > 0 else -999
        good = db >= 6
        if good:
            hits += 1
        print("   %-5d %-14.1f %-14.1f %-12d %.1f  %s"
              % (i + 1, b_e, p_e, pk, db, "✓" if good else "✗"))
    print()
    print("   成功 %d/%d" % (hits, a.reps))
    print()

    # ══════════════════════════════ ③ 全程录（不设窗口）
    print("③ 一边放一边从头录到底（不设采集窗口）")
    p = subprocess.Popen(["aplay", "-q", "-D", PLAY_DEV, wav],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.1)
    subprocess.run(["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE",
                    "-c", "2", "-r", str(RATE), "-d", str(int(a.secs) + 1),
                    "-t", "raw"],
                   stdout=open("/tmp/_tim_full.raw", "wb"),
                   stderr=subprocess.DEVNULL)
    try:
        p.wait(timeout=a.secs + 5)
    except Exception:
        p.kill()
    rms, pk = rms_and_peak("/tmp/_tim_full.raw")
    print("   全程 RMS %.0f  峰值 %d（满量程 8388608）" % (rms, pk))
    print()

    print("=" * 78)
    print(" 判读")
    print("=" * 78)
    print(" ★ ② 成功率高（>=80%）→ 之前的不稳定是【测量窗口】的问题：")
    print("     短音 + arecord 启动慢 → 没对上。修法：音放长一点、")
    print("     或者先起 arecord 再起 aplay。")
    print(" ★ ② 成功率还是低    → I2S/DMA 层确实不稳，要继续查")
    print(" ★ 如果 arecord 启动 > 300ms，那基本就能确定是它")


if __name__ == "__main__":
    main()
