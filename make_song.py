#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_song.py —— 合成一首真正的曲子（卡农 Canon in D）

为什么不用现成的测试音：
  * 之前的 01_纯音/04_扫频 是测试信号，不是音乐，听着"不响"
  * 小星星 是单音旋律，没有编曲，响度上不去
  * **关键：我之前做的是【峰值】归一化，但峰值≠响度。**
    真正决定"听着响不响"的是 RMS（有效值）。这里按 RMS 归一化。

做法：
  * Canon in D 的和声进行 + 琶音 + 旋律 + 低音
  * 加法合成（多个谐波 + 指数衰减）模拟钢琴/拨弦
  * ADSR 包络
  * 最后按 RMS 归一到目标响度，并用软限幅把峰值压在 -1 dBFS 以内
"""
import math
import os
import struct
import sys
import wave

try:
    import numpy as np
    HAVE_NP = True
except ImportError:
    HAVE_NP = False

SR = 44100
OUT = sys.argv[1] if len(sys.argv) > 1 else r"D:\ubuntu_iso\卡农.wav"
TARGET_RMS_DB = -10.0          # 目标响度（流行音乐通常 -14 ~ -9 dBFS）
PEAK_CEIL_DB = -1.0            # 峰值上限

# 音名 -> 频率
def nf(name):
    """把 'D4' 这样的音名转成频率"""
    base = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
            "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    n = name[:-1]
    octv = int(name[-1])
    semi = base[n] + (octv - 4) * 12
    return 440.0 * (2.0 ** (semi / 12.0))


# ── Canon in D 的和声进行（8 小节，每小节 2 秒）────────────────────
# 低音（每小节一个长音）
BASS = ["D3", "A2", "B2", "F#2", "G2", "D3", "G2", "A2"]
# 和弦（用于琶音和铺底）
CHORDS = [
    ["D3", "F#3", "A3", "D4"], ["A2", "C#4", "E4", "A3"],
    ["B2", "D4", "F#4", "B3"], ["F#2", "A3", "C#4", "F#3"],
    ["G2", "B3", "D4", "G3"], ["D3", "F#3", "A3", "D4"],
    ["G2", "B3", "D4", "G3"], ["A2", "C#4", "E4", "A3"],
]
# 旋律（每小节 4 个音，None = 休止）
MELODY = [
    ["F#5", "E5", "D5", "C#5"], ["D5", "C#5", "B4", "A4"],
    ["B4", "A4", "G4", "F#4"], ["G4", "F#4", "E4", "D4"],
    ["G4", "A4", "B4", "C#5"], ["D5", "C#5", "B4", "A4"],
    ["B4", "C#5", "D5", "E5"], ["F#5", "E5", "D5", "C#5"],
]

BAR_SEC = 2.0
NOTE_SEC = BAR_SEC / 4.0


def gen_note(freq, dur, amp=0.5, harmonics=None, decay=3.2, attack=0.006):
    """加法合成一个音：多个谐波 + 指数衰减"""
    if harmonics is None:
        # 钢琴/拨弦味：基频 + 递减的谐波
        harmonics = [(1, 1.00), (2, 0.42), (3, 0.24), (4, 0.13),
                     (5, 0.08), (6, 0.05), (8, 0.03), (10, 0.02)]
    n = int(SR * dur)
    if n <= 0:
        return np.zeros(0) if HAVE_NP else []
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for mult, hamp in harmonics:
        f = freq * mult
        if f > SR / 2 * 0.95:
            continue                      # 超过奈奎斯特就丢掉
        sig += hamp * np.sin(2 * math.pi * f * t)
    # 指数衰减包络 + 短促 attack（避免咔哒声）
    env = np.exp(-decay * t)
    a = max(1, int(SR * attack))
    env[:a] *= np.linspace(0.0, 1.0, a)
    # 收尾淡出，避免截断爆音
    r = min(n, int(SR * 0.03))
    if r > 1:
        env[-r:] *= np.linspace(1.0, 0.0, r)
    return sig * env * amp


def main():
    if not HAVE_NP:
        print("需要 numpy")
        return 1

    total = int(SR * BAR_SEC * len(BASS))
    mix = np.zeros(total)

    def add(sig, at):
        i = int(at * SR)
        j = min(total, i + len(sig))
        if j > i:
            mix[i:j] += sig[:j - i]

    for bar in range(len(BASS)):
        t0 = bar * BAR_SEC

        # ① 低音：整小节长音
        add(gen_note(nf(BASS[bar]), BAR_SEC * 1.6, amp=0.42,
                     harmonics=[(1, 1.0), (2, 0.30), (3, 0.12)], decay=1.6), t0)

        # ② 和弦铺底：四个音一起轻铺
        for note in CHORDS[bar]:
            add(gen_note(nf(note), BAR_SEC * 1.1, amp=0.10, decay=2.6), t0)

        # ③ 琶音：把和弦音分解成 8 个八分音符（卡农的招牌）
        pat = CHORDS[bar]
        for k in range(8):
            note = pat[k % len(pat)]
            f = nf(note) * (2.0 if k >= 4 else 1.0)
            add(gen_note(f, NOTE_SEC * 1.6, amp=0.16, decay=4.5),
                t0 + k * (BAR_SEC / 8.0))

        # ④ 旋律：4 个四分音符，最突出
        for k, note in enumerate(MELODY[bar]):
            if note is None:
                continue
            add(gen_note(nf(note), NOTE_SEC * 2.2, amp=0.34, decay=2.4),
                t0 + k * NOTE_SEC)

    # ── 电平处理 ────────────────────────────────────────────────
    def rms_db(x):
        r = math.sqrt(float(np.mean(x.astype(np.float64) ** 2)))
        return 20 * math.log10(max(1e-12, r / 32767.0))

    def peak_db(x):
        return 20 * math.log10(max(1e-12, float(np.max(np.abs(x))) / 32767.0))

    x = mix / max(1e-9, float(np.max(np.abs(mix)))) * 32767.0 * 0.95
    print("  归一化到峰值后:  RMS %.1f dBFS   峰值 %.1f dBFS"
          % (rms_db(x), peak_db(x)))

    # 按 RMS 提响度，但峰值不许超过上限
    want = 32767.0 * (10 ** (TARGET_RMS_DB / 20.0))
    cur = math.sqrt(float(np.mean(x.astype(np.float64) ** 2)))
    gain = want / max(1e-9, cur)
    ceil = 32767.0 * (10 ** (PEAK_CEIL_DB / 20.0))
    if float(np.max(np.abs(x))) * gain > ceil:
        gain = ceil / max(1e-9, float(np.max(np.abs(x))))
        print("  （峰值会超上限，改用峰值约束增益）")
    x = x * gain
    print("  响度归一化后:    RMS %.1f dBFS   峰值 %.1f dBFS"
          % (rms_db(x), peak_db(x)))

    # 多级软限幅：每级温和压缩，累积起来能把 RMS 提上去而听感不破
    # （比一次性硬压好听得多；用户之前明确反感重压缩的失真感）
    for stage in range(5):
        thr = 32767.0 * (0.86 - stage * 0.09)
        over = np.abs(x) > thr
        if not np.any(over):
            break
        s = np.sign(x[over])
        a = np.abs(x[over])
        x[over] = s * (thr + (32767.0 - thr) *
                       np.tanh((a - thr) / (32767.0 - thr)))
        # 每压一次就把整体抬一点，把省下来的动态换成响度
        if stage < 4:
            cur_rms = math.sqrt(float(np.mean(x.astype(np.float64) ** 2)))
            want_rms = 32767.0 * (10 ** (TARGET_RMS_DB / 20.0))
            if cur_rms < want_rms:
                x = x * min(1.30, want_rms / max(1e-9, cur_rms))
    print("  软限幅后:        RMS %.1f dBFS   峰值 %.1f dBFS"
          % (rms_db(x), peak_db(x)))

    # 转 16bit 立体声（左右相同）
    v = np.clip(np.round(x), -32768, 32767).astype(np.int16)
    st = np.empty(v.size * 2, dtype=np.int16)
    st[0::2] = v
    st[1::2] = v

    w = wave.open(OUT, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(st.tobytes())
    w.close()

    print()
    print("  已生成: %s" % OUT)
    print("  %.2f 秒  %d 字节  44100Hz 16bit 立体声"
          % (len(v) / float(SR), os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
