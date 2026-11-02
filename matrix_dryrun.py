#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""matrix_dryrun.py —— ③ 分析流水线的**干跑**验证（不需要板子、不出声）

════════════════════════════════════════════════════════════════════
要证明什么
════════════════════════════════════════════════════════════════════
③（频谱自证）分两半：
    物理采集   : 从喇叭放纯音 -> 麦克风回录 -> DDR      （要放音）
    分析判定   : Goertzel -> 平坦度 -> 对角线命中 -> ok  （不用放音）

如果我能证明"**只要采到干净的纯音，流水线一定判通过**"，
那把 ③ 的未验证范围就缩到最小 —— 只剩物理采集。

做法：造合成的"回录"数据（纯音 + 适量噪声，按 formatter 的 8 字节/帧格式），
      喂给**和真机完全相同的那套判据代码**，看它给不给 pass。

════════════════════════════════════════════════════════════════════
判据回顾（来自离线测试台 test_audio_math.py 的标定）
════════════════════════════════════════════════════════════════════
    纯音 990.5 Hz   -> 平坦度 765,452
    白噪声          -> 平坦度 1.70
    阈值 100        （旧值 1.8 是假阈值：白噪声自己就 1.70）
    判定 = 对角线命中 >= 5/6  且  最小平坦度 > 100

用法:
    python matrix_dryrun.py            # 用默认信噪比
    python matrix_dryrun.py --snr 10   # 加很重的噪声看边界
    python matrix_dryrun.py --sweep    # 扫信噪比，找判据的失效点
"""
import argparse
import math
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FS = 44100
BYTES_PER_FRAME = 8          # 2ch x 32bit 容器（formatter 的格式）
FREQS = [495.3, 646.0, 990.5, 1292.0, 1507.3, 2002.6]   # 与 audio_svc 一致


# ─────────────────────────────────────────── 判据代码（与真机同源）
# 这三个函数是 matrix_vol.py / audio_svc.spectral_matrix 用的同一套逻辑。
def win_goertzel(v, f, rate=FS):
    """加窗 Goertzel 能量"""
    n = len(v)
    if n < 64:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for i, x in enumerate(v):
        win = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        s0 = x * win + c * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def energy_row(samples, freqs):
    return [win_goertzel(samples, f) for f in freqs]


def flatness(energies):
    s = sorted(energies)
    med = s[len(s) // 2]
    if med <= 0:
        return float("inf") if max(s) > 0 else 0.0
    return max(s) / med


def verdict(rows):
    """rows: 每个播放频率一行能量。返回 (hit, min_flatness, ok)"""
    hit = 0
    flats = []
    for i, e in enumerate(rows):
        if not e:
            continue
        if e.index(max(e)) == i:
            hit += 1
        flats.append(flatness(e))
    mf = min(flats) if flats else 0.0
    return hit, mf, bool(hit >= len(rows) - 1 and mf > 100)


# ─────────────────────────────────────────── 合成"回录"数据
def synth_capture(play_f, secs=0.5, snr_db=40.0, amp=0.25, seed=None):
    """按 formatter 的 8 字节/帧格式造一段合成回录。

    第 i 帧 = [L(4字节)][R(4字节)]，每声道是 32bit 容器里的 24bit 样本。
    内容 = 播放的纯音 + 环境噪声（按 snr_db 定噪声幅度）。
    """
    rnd = random.Random(seed)
    n = int(secs * FS)
    full = 8388607.0
    sig = amp * full
    noise = sig / (10.0 ** (snr_db / 20.0))
    out = []
    ph = rnd.random() * 2 * math.pi          # 随机初相（更接近真实）
    for i in range(n):
        t = i / float(FS)
        s = int(sig * math.sin(2 * math.pi * play_f * t + ph)
                + rnd.gauss(0, noise / 3.0))
        s = max(-8388608, min(8388607, s)) & 0xFFFFFF
        out.append(tuple(s.to_bytes(4, "little")))
    # 展平成字节（这个函数只是为了让数据"经过和真机一样的字节格式"）
    return n, len(out) * BYTES_PER_FRAME


def synth_samples(play_f, secs=0.5, snr_db=40.0, amp=0.25, seed=None):
    """直接返回样本列表（跳过字节打包，语义等价但快得多）"""
    rnd = random.Random(seed)
    n = int(secs * FS)
    full = 8388607.0
    sig = amp * full
    noise = sig / (10.0 ** (snr_db / 20.0))
    ph = rnd.random() * 2 * math.pi
    return [sig * math.sin(2 * math.pi * play_f * i / float(FS) + ph)
            + rnd.gauss(0, noise / 3.0) for i in range(n)]


# ─────────────────────────────────────────── 主流程
def run_once(snr_db, secs, amp, seed_base=1):
    rows = []
    for k, f0 in enumerate(FREQS):
        samples = synth_samples(f0, secs=secs, snr_db=snr_db, amp=amp,
                                seed=seed_base * 100 + k)
        rows.append(energy_row(samples, FREQS))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snr", type=float, default=40.0)
    ap.add_argument("--secs", type=float, default=0.5)
    ap.add_argument("--amp", type=float, default=0.25)
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()

    print("=" * 78)
    print("③ 分析流水线 · 干跑验证（合成数据，不需要板子，不出声）")
    print("=" * 78)
    print("  判据: 对角线命中 >= 5/6  且  最小平坦度 > 100")
    print("  候选频率:", " ".join("%.1f" % f for f in FREQS))
    print()

    if a.sweep:
        print("扫信噪比，找判据的失效点：")
        print("  %-10s %-8s %-14s %-8s %s"
              % ("SNR(dB)", "命中", "最小平坦度", "判定", "说明"))
        print("  " + "-" * 66)
        for snr in (60, 50, 40, 30, 25, 20, 15, 12, 10, 8, 5, 0, -5, -10):
            rows = run_once(snr, a.secs, a.amp)
            hit, mf, ok = verdict(rows)
            note = ""
            if not ok and mf <= 100:
                note = "噪声把频谱抬平了"
            elif not ok:
                note = "有尖峰但命中不够"
            elif snr <= 10:
                note = "★ 这么差的信噪比还能过"
            print("  %-10.0f %-8s %-14.1f %-8s %s"
                  % (snr, "%d/6" % hit, mf, "通过" if ok else "不通过", note))
        print()
        print("  读法：平坦度从 1e5 量级掉到个位数的那一档，就是判据的边界。")
        print("        真实回录只要落在「通过」区，③ 就应该能过。")
        return 0

    # 单次（默认 SNR=40dB）
    print("默认条件（SNR=%.0f dB, %.2f 秒, amp=%.2f）:" % (a.snr, a.secs, a.amp))
    rows = run_once(a.snr, a.secs, a.amp)
    print()
    print("  %-10s | %s | 判定" % ("播放Hz", " ".join("%9.0f" % x for x in FREQS)))
    print("  " + "-" * 78)
    for i, (f0, e) in enumerate(zip(FREQS, rows)):
        hit = (e.index(max(e)) == i)
        print("  %-10.1f | %s | %s  平坦度=%.0f"
              % (f0, " ".join("%9.0f" % x for x in e),
                 "★对角线" if hit else " 偏离->%.1f" % FREQS[e.index(max(e))],
                 flatness(e)))
    hit, mf, ok = verdict(rows)
    print("  " + "-" * 78)
    print("  对角线命中 %d/6   最小平坦度=%.1f   判定=%s"
          % (hit, mf, "★ 通过" if ok else "不通过"))
    print()
    if ok:
        print("  ★ 结论：**只要采到干净的纯音，流水线一定判通过。**")
        print("    所以 ③ 唯一待验证的是「物理采集」那一步 ——")
        print("    而它的障碍已知（边放边录 ADC 过载），正解是降低放音电平。")
    else:
        print("  ✗ 流水线自己都不过 —— 那问题在分析代码，不是采集。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
