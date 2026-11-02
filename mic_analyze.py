#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mic_analyze.py —— 判断录到的是「人声」还是「电气噪声」

判据：
  * 人声：能量集中在 100~3000 Hz，且有**音节级包络起伏**（每 0.1~0.3 秒强弱变化）
  * 电气哼声：能量压在 50/100 Hz 附近，包络几乎不动
  * 宽带噪声：频谱平坦，无包络结构

故意不依赖人耳 —— 用数字说话。
"""
import glob
import io
import math
import os
import struct
import sys
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = "/tmp/mic_chunks"
RATE = 16000


def goe(v, f, rate):
    n = len(v)
    if n < 64:
        return 0.0
    w = 2 * math.pi * f / rate
    c = 2 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for i, x in enumerate(v):
        win = 0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))
        s0 = x * win + c * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def load(p):
    w = wave.open(p, "rb")
    n = w.getnframes()
    d = w.readframes(n)
    return list(struct.unpack("<%dh" % (len(d) // 2), d)), w.getframerate()


files = sorted(glob.glob(os.path.join(D, "*.wav")))
if not files:
    print("没有录音文件")
    sys.exit(1)

# 挑最响的几段
scored = []
for p in files:
    try:
        v, r = load(p)
    except Exception:
        continue
    if not v:
        continue
    rms = math.sqrt(sum(float(x) * x for x in v) / len(v))
    scored.append((rms, p, v, r))
scored.sort(key=lambda x: -x[0])

print("=" * 78)
print("录到的内容分析（共 %d 段，按响度排前 3）" % len(scored))
print("=" * 78)

BANDS = [50, 100, 200, 400, 800, 1600, 3000, 6000]
for rms, p, v, r in scored[:3]:
    n = len(v)
    dur = n / float(r)
    # 各频段能量
    e_low = goe(v, 50, r) + goe(v, 100, r)
    e_speech = sum(goe(v, f, r) for f in (200, 400, 800, 1600, 3000))
    e_high = goe(v, 6000, r)
    tot = max(1e-9, e_low + e_speech + e_high)
    # 包络起伏：切成 20 段看 RMS 的变异系数
    seg = max(1, n // 20)
    segrms = []
    for i in range(20):
        s = v[i * seg:(i + 1) * seg]
        if s:
            segrms.append(math.sqrt(sum(float(x) * x for x in s) / len(s)))
    mean = sum(segrms) / max(1, len(segrms))
    var = sum((x - mean) ** 2 for x in segrms) / max(1, len(segrms))
    cv = math.sqrt(var) / max(1e-9, mean)      # 变异系数

    print()
    print("%s" % os.path.basename(p))
    print("  时长 %.1fs   RMS=%.1f  峰值=%d" % (dur, rms, max(abs(x) for x in v)))
    print("  能量分布: 低频(50/100Hz) %.1f%%  语音带(200~3kHz) %.1f%%  高频(6k) %.1f%%"
          % (100 * e_low / tot, 100 * e_speech / tot, 100 * e_high / tot))
    print("  包络起伏 CV = %.2f  (人声说话通常 >0.5；稳态噪声 <0.2)" % cv)
    verdict = []
    if e_speech / tot > 0.4:
        verdict.append("语音带占优")
    if e_low / tot > 0.5:
        verdict.append("低频占优(可能是哼声/工频)")
    if cv > 0.45:
        verdict.append("有音节级起伏(像说话)")
    elif cv < 0.2:
        verdict.append("包络很平(像稳态噪声)")
    print("  判读:", " + ".join(verdict) if verdict else "不典型")
    v2 = " ".join("%5.0f" % x for x in segrms)
    print("  20 段包络:", v2)
