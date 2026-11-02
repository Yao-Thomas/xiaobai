#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_diag.py —— 对比「文件打包」和「make_sine」的字节，找出为什么文件没声音"""
import struct
import sys

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_svc as S
import audio_pl as A

print("=" * 84)
print("打包对比：文件 vs make_sine")
print("=" * 84)

# ---- 1) 读文件 ----
P = "/home/zynq/Music/03_小星星.wav"
samples, rate, ch = S.read_wav(P)
print("  read_wav: %d 个样本, rate=%d, 声道=%d" % (len(samples), rate, ch))
print("    前 12 个样本:", samples[:12])
print("    最大绝对值  :", max(abs(x) for x in samples))

# ---- 2) 用服务的 _pack_stream 打包（需要一个实例）----
class FakeOut(object):
    pack = "rj"
    ring = 65536

class FakeSvc(object):
    out = FakeOut()
    _pack_stream = S.Engine._pack_stream

fs = FakeSvc()
pcm = fs._pack_stream(samples, channels=ch, rate=rate)
print()
print("  _pack_stream: %d 字节" % len(pcm))
print("    前 16 字节:", " ".join("%02X" % b for b in pcm[:16]))

# ---- 3) 解回 int32 看样本值 ----
vals = [struct.unpack("<I", pcm[4 * i:4 * i + 4])[0] for i in range(min(8, len(pcm) // 4))]
print("    前 8 个 32bit 字: %s" % ["0x%08X" % v for v in vals])
print("    （rj 约定：低 24 位是样本）")
sgn = [(v & 0xFFFFFF) - 0x1000000 if (v & 0x800000) else (v & 0xFFFFFF)
       for v in vals]
print("    解成有符号 24bit :", sgn)

# ---- 4) make_sine 对照 ----
tone = A.make_sine(990.5, frames=8, amp=0.9, pack="rj")
tvals = [struct.unpack("<I", tone[4 * i:4 * i + 4])[0] for i in range(8)]
print()
print("  make_sine(amp=0.9) 前 8 个 32bit 字:")
print("    %s" % ["0x%08X" % v for v in tvals])
tsgn = [(v & 0xFFFFFF) - 0x1000000 if (v & 0x800000) else (v & 0xFFFFFF)
        for v in tvals]
print("    解成有符号 24bit :", tsgn)

# ---- 5) 峰值对比 ----
import math
pcm_vals = []
for i in range(len(pcm) // 4):
    v = struct.unpack("<I", pcm[4 * i:4 * i + 4])[0] & 0xFFFFFF
    if v & 0x800000:
        v -= 0x1000000
    pcm_vals.append(v)
pk_file = max(abs(x) for x in pcm_vals)
rms_file = math.sqrt(sum(float(x) * x for x in pcm_vals) / len(pcm_vals))
pk_tone = max(abs(x) for x in tsgn) if tsgn else 0

print()
print("  文件打包后: 峰值=%d  RMS=%.0f" % (pk_file, rms_file))
print("  纯音(0.9) : 峰值≈%d" % int(0.9 * 8388607))
print("  满量程    : 8388607")
print("  文件相对纯音: %.1f dB" % (20 * math.log10(max(1e-9, pk_file)
                                              / max(1e-9, 0.9 * 8388607))))

# ---- 6) 关键：文件开头的 0.186 秒（一个环）有多响 ----
ring_frames = 65536 // 8
first = pcm_vals[:ring_frames * 2]
print()
print("  开头 %d 帧（= 一个播放环）的峰值 = %d"
      % (ring_frames, max(abs(x) for x in first) if first else 0))
print("  => 这决定了「只播一个环」时听不听得见")
