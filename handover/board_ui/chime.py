#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chime.py —— 正常好听的**提示音**（手机通知那种两声短铃）

为什么做这个：
  之前做声学自证时用的是原始正弦 / 蜂鸣器方波，既刺耳又反复响，很扰人。
  改成"手机通知音"风格：两声短铃 + 指数衰减 + 少量谐波，
  总时长约 0.5 秒、音量可控，听起来就是正常的提示音。

同时它对频谱分析依然有效：两个音的音高是精确已知的
（E6=1318.51Hz、A6=1760.00Hz），麦克风回录后能直接找出这两个峰。

用法:
    python3 chime.py                    # 只生成，不播放
    python3 chime.py --play             # 生成并播一次（约 0.5 秒）
    python3 chime.py --out /path.wav
    python3 chime.py --style huawei     # 另一种音型
"""
import argparse
import math
import os
import struct
import time
import wave

RATE = 44100
E6 = 1318.51
A6 = 1760.00
C6 = 1046.50
G6 = 1567.98
E7 = 2637.02
A7 = 3520.00

STYLES = {
    # (基频, 起始时间, 时长)  —— 都是"铃"的音色（指数衰减+谐波）
    "apple":   [(E6, 0.00, 0.30), (A6, 0.16, 0.34)],          # 两声上行(常见通知)
    "huawei":  [(C6, 0.00, 0.22), (E6, 0.13, 0.22), (G6, 0.26, 0.34)],
    "ding":    [(880.00, 0.00, 0.55)],                        # 单声长铃 A5
    "dong":    [(880.00, 0.00, 0.34), (587.33, 0.22, 0.45)],  # 叮-咚(下行)
    "up":      [(C6, 0.00, 0.20), (G6, 0.11, 0.32)],          # 快速两声
    "soft":    [(659.26, 0.00, 0.34), (880.00, 0.20, 0.42)],  # 低八度柔和 E5->A5
    "pop":     [(A6, 0.00, 0.16)],                            # 很短一声
    "echo":    [(A6, 0.00, 0.24), (A6, 0.18, 0.20), (A6, 0.34, 0.30)],
    # ---- 下面几个是"明显更响"的：延音更长 + 包络压缩 + 更高的音（见 COMP）----
    "loud":    [(A6, 0.00, 1.10)],                            # 一声长铃，能量最高
    "big":     [(A6, 0.00, 0.55), (E7, 0.22, 0.85)],          # 双音长铃
    "hi":      [(A7, 0.00, 0.42)],                            # 高八度：小喇叭效率最高
    "hi2":     [(E7, 0.00, 0.28), (A7, 0.15, 0.52)],
    # ---- 平包络：能量≈峰值，这是这套硬件能发出的**最响** ----
    "max":     [(A6, 0.00, 0.50)],
    "maxhi":   [(E7, 0.00, 0.45)],
}

# 平包络（不衰减）——平均能量=峰值，最响；就是普通"哔"声，不花哨
FLAT = {"max", "maxhi"}

# 包络压缩指数：<1 会把衰减的尾巴抬起来 => 平均能量（=听感响度）大幅提高，
# 而峰值不变（所以不会削顶）。1.0 = 不压缩。
COMP = {"loud": 0.42, "big": 0.50, "hi": 0.55, "hi2": 0.55}

# 给界面用的中文名
STYLE_NAMES = {
    "apple": "上行两声", "huawei": "三声", "ding": "单声长铃",
    "dong": "叮-咚", "up": "快速两声", "soft": "柔和", "pop": "短促",
    "echo": "回声",
    "loud": "长铃(响)", "big": "双音长铃(响)", "hi": "高音(响)", "hi2": "高音两声(响)",
    "max": "最大声", "maxhi": "最大声(高音)",
}


def make_chime(style="apple", rate=RATE, amp=0.95):
    """返回 int16 单声道样本。带指数衰减 + 轻谐波，听感像铃不是"哔"。

    ★ 关于"声音小"：实测满量程 1kHz 正弦的 RMS 是 -3.0 dBFS，
      而普通提示音只有 -13.6 dBFS（衰减太快，平均能量只有峰值 21%）。
      COMP 里列出的几个风格用 env**g 压缩包络把尾巴抬起来，
      峰值不变、平均能量提高，听感明显更响。
    """
    notes = STYLES.get(style, STYLES["apple"])
    g = COMP.get(style, 1.0)
    total = max(t0 + d for _, t0, d in notes) + 0.05
    n = int(total * rate)
    buf = [0.0] * n
    for f, t0, dur in notes:
        i0 = int(t0 * rate)
        nlen = int(dur * rate)
        for k in range(nlen):
            t = k / float(rate)
            if style in FLAT:
                # 平包络：只留 8ms 淡入 / 30ms 淡出，其余保持 1.0
                env = 1.0
                if t < 0.008:
                    env = t / 0.008
                elif t > dur - 0.03:
                    env = max(0.0, (dur - t) / 0.03)
            else:
                env = math.exp(-6.0 * t / dur) * (1.0 - math.exp(-400.0 * t))
                if g < 1.0:
                    env = env ** g
            # 基频 + 两个衰减更快的谐波 => 铃感
            s = (math.sin(2 * math.pi * f * t)
                 + 0.32 * math.sin(2 * math.pi * 2 * f * t) * math.exp(-3.0 * t / dur)
                 + 0.12 * math.sin(2 * math.pi * 3 * f * t) * math.exp(-5.0 * t / dur))
            j = i0 + k
            if j < n:
                buf[j] += s * env
    pk = max((abs(x) for x in buf), default=1.0) or 1.0
    g = amp * 32767.0 / pk
    return [max(-32768, min(32767, int(x * g))) for x in buf]


def write_wav(samples, path, rate=RATE):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % len(samples), *samples))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="apple", choices=list(STYLES))
    ap.add_argument("--out", default="/home/zynq/Music/提示音.wav")
    ap.add_argument("--amp", type=float, default=0.95)
    ap.add_argument("--play", action="store_true")
    a = ap.parse_args()

    s = make_chime(a.style, amp=a.amp)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    write_wav(s, a.out)
    print("提示音已生成: %s  (%.2f 秒, %d 样本, 峰值 %d)"
          % (a.out, len(s) / float(RATE), len(s), max(abs(x) for x in s)))

    if a.play:
        import json
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:8767/play",
            data=json.dumps({"file": a.out}).encode(),
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=30) as r:
            print("播放结果:", r.read().decode(), "(%.2fs)" % (time.time() - t0))


if __name__ == "__main__":
    main()
