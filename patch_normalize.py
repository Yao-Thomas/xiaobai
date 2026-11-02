#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_normalize.py —— 给文件播放加**自动增益归一化**

═══ 为什么 ═══
实测对比（同一套 codec 设置）：

    纯音 make_sine(amp=0.9) : 峰值 7549746 (-1 dBFS)   -> 用户听到"超级大"
    03_小星星.wav           : 峰值 2987264 (-9 dBFS)   -> 听不到

再叠加音量档位差异（33 = +4.5dB vs 20 = -15dB），
有效电平差了 27.5 dB —— 所以"播文件没声音"其实是**音量太小**。

另外一个独立 bug：原来 `_fill_ring` 只灌**一个播放环**（0.186 秒）就循环，
而《小星星》开头 8192 帧的峰值正好是 **0**（纯静音淡入）——
所以哪怕音量够，也只会听到 0.186 秒的静音无限循环。

两条都修：
  1. 流式播放（上一步已修）
  2. **自动归一化**：把峰值提到目标档位，这样文件播放和纯音一样饱满
"""
import io
import sys

P = "ui/audio_svc.py"
src = io.open(P, encoding="utf-8").read()

if "TARGET_PEAK" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

OLD = '''        if channels == 1:
            samples = [x for x in samples for _ in (0, 1)]
        if rate != FS:
            n = len(samples)
            out_n = int(n * FS / float(rate))
            step = rate / float(FS)
            out = []
            for k in range(out_n):
                p = k * step
                i0 = int(p)
                i1 = min(i0 + 1, n - 1)
                f = p - i0
                out.append(int(samples[i0] * (1 - f) + samples[i1] * f))
            samples = out
        buf = bytearray()
'''

NEW = '''        if channels == 1:
            samples = [x for x in samples for _ in (0, 1)]
        if rate != FS:
            n = len(samples)
            out_n = int(n * FS / float(rate))
            step = rate / float(FS)
            out = []
            for k in range(out_n):
                p = k * step
                i0 = int(p)
                i1 = min(i0 + 1, n - 1)
                f = p - i0
                out.append(int(samples[i0] * (1 - f) + samples[i1] * f))
            samples = out

        # ★★ 自动归一化（2026-09-28 加）
        #   实测：纯音 amp=0.9 的峰值 7549746 用户听着"超级大"，
        #   而 03_小星星.wav 峰值只有 2987264（-9dBFS）-> 听不到。
        #   再叠加音量档位（33 vs 20）差 27.5 dB。
        #   所以这里把峰值提到目标档位，让文件播放和纯音一样饱满。
        #   GAIN_MAX 限幅：本来就很响的文件不会被放大到削波。
        pk = 0
        for x in samples:
            ax = x if x >= 0 else -x
            if ax > pk:
                pk = ax
        if pk > 0:
            g = TARGET_PEAK / float(pk)
            if g > GAIN_MAX:
                g = GAIN_MAX
            if abs(g - 1.0) > 0.01:
                samples = [int(x * g) for x in samples]

        buf = bytearray()
'''
assert OLD in src, "_pack_stream 锚点没找到"
src = src.replace(OLD, NEW, 1)

# 在 _pack_stream 之前插入常量
anchor2 = '''    def _pack_stream(self, samples, channels=1, rate=FS):'''
consts = '''    # ★ 归一化目标：峰值提到 int16 满量程的 90%（≈ -1 dBFS，和 amp=0.9 的纯音相当）
    TARGET_PEAK = int(0.90 * 32767)
    # 最大放大倍数（避免把一段极安静的录音抬成噪声墙）
    GAIN_MAX = 12.0

'''
assert anchor2 in src, "常量插入锚点没找到"
src = src.replace(anchor2, consts + anchor2, 1)

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
print("  TARGET_PEAK = 90% 满量程；GAIN_MAX = 12 倍")
