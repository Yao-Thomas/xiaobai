#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wav_audit.py —— 查音乐目录里每个 WAV 的真实电平

假设：`/play {"file":...}` 没声音，是因为**文件本身几乎没有内容**。
"""
import glob
import math
import os
import struct
import sys
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

files = sorted(glob.glob("/home/zynq/Music/*.wav"))
print("=" * 96)
print("音乐目录 WAV 审计（%d 个）" % len(files))
print("=" * 96)
print()
print("%-26s %8s %5s %8s %9s %11s %9s %s"
      % ("文件", "Hz", "声道", "位宽", "秒", "RMS", "峰值", "判定"))
print("-" * 96)

for p in files:
    try:
        w = wave.open(p, "rb")
        ch, sw, r, n = (w.getnchannels(), w.getsampwidth(),
                        w.getframerate(), w.getnframes())
        raw = w.readframes(n)
        w.close()
    except Exception as e:
        print("%-26s 打不开: %s" % (os.path.basename(p), e))
        continue

    # 解成 int16 量级
    if sw == 1:
        v = [(b - 128) << 8 for b in raw]
    elif sw == 2:
        v = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    elif sw == 3:
        v = []
        for i in range(len(raw) // 3):
            x = int.from_bytes(raw[3 * i:3 * i + 3], "little")
            if x & 0x800000:
                x -= 0x1000000
            v.append(x >> 8)
    elif sw == 4:
        v = [struct.unpack("<i", raw[4 * i:4 * i + 4])[0] >> 16
             for i in range(len(raw) // 4)]
    else:
        v = []

    if not v:
        print("%-26s (无样本)" % os.path.basename(p))
        continue

    rms = math.sqrt(sum(float(x) * x for x in v) / len(v))
    pk = max(abs(x) for x in v)
    dur = n / float(r)
    nz = sum(1 for x in v if abs(x) > 16) / float(len(v))

    if pk < 64:
        verdict = "★全静音/近静音"
    elif rms < 100:
        verdict = "★极小声"
    else:
        verdict = "有内容"

    print("%-26s %8d %5d %7dbit %9.2f %11.1f %9d %s (非零%.0f%%)"
          % (os.path.basename(p)[:26], r, ch, sw * 8, dur, rms, pk,
             verdict, nz * 100))

print()
print("★ 判读：RMS < 100 或 峰值 < 64 的文件，播出来几乎听不见。")
print("        `play_tone` 是现场按 amp 合成的，所以不受文件影响 ——")
print("        这就解释了「纯音超大声、播文件没声音」。")
