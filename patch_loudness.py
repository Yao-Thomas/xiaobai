#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_loudness.py —— 给文件播放加**响度提升（软限幅）**

═══ 实测数据 ═══
A/B 对比（同样音量 33、同样输出配置、同一支麦克风回录）：

    基线(静音)          总RMS    141009
    C 纯音(峰值7.5M)    总RMS   4866252     <- 用户听"超级大"
    B 文件(峰值7.5M)    总RMS    670894     <- 用户"没声音"
    A 文件(流式)        总RMS    769258

**两者峰值一样，但 RMS 差 13.8 倍（-17 dB）。**

原因：**波峰因数（crest factor）**
    正弦:  RMS/峰值 = 0.58 ~ 0.707
    音乐:  RMS/峰值 ≈ 0.13

所以"峰值归一化"对音乐是不够的 —— 音乐的峰值偶尔冲得高，
但大部分时间能量很低，听起来就"没劲/听不见"。

═══ 修法 ═══
两级处理：
  1. 先按峰值归一化到 0.95（保证不削顶）
  2. **软限幅（tanh）** 把能量密度压上来 —— 这是广播/流媒体
     让音乐"响"起来的经典做法。用 tanh 而不是硬削，听感更自然
     （硬削会产生刺耳的高次谐波）。

DRIVE 是可调的"推多少"。1.0 = 不推，越大越响也越压缩。
"""
import io
import sys

P = "ui/audio_svc.py"
src = io.open(P, encoding="utf-8").read()

if "SOFT_CLIP_DRIVE" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ---- 1) 加常量
old_const = '''    # 最大放大倍数（避免把一段极安静的录音抬成噪声墙）
    GAIN_MAX = 12.0'''
new_const = '''    # 最大放大倍数（避免把一段极安静的录音抬成噪声墙）
    GAIN_MAX = 12.0
    # ★ 软限幅推动量（2026-09-28 加）
    #   实测：峰值相同的纯音和音乐，回录 RMS 差 13.8 倍（-17 dB）。
    #   根因是波峰因数（正弦 0.58~0.707，音乐约 0.13）。
    #   用 tanh 软限幅把能量密度提上来，让音乐听起来和纯音一样"有劲"。
    #   1.0 = 不推；2.0 = 中等；3.0 = 比较激进（会有可闻压缩）
    SOFT_CLIP_DRIVE = 2.2'''
assert old_const in src, "常量锚点没找到"
src = src.replace(old_const, new_const, 1)
print("  OK: 加 SOFT_CLIP_DRIVE 常量")

# ---- 2) 归一化那段改成"峰值归一化 + 软限幅"
old_norm = '''        pk = 0
        for x in samples:
            ax = x if x >= 0 else -x
            if ax > pk:
                pk = ax
        if pk > 0:
            g = self.TARGET_PEAK / float(pk)
            if g > self.GAIN_MAX:
                g = self.GAIN_MAX
            if abs(g - 1.0) > 0.01:
                samples = [int(x * g) for x in samples]
'''
new_norm = '''        pk = 0
        for x in samples:
            ax = x if x >= 0 else -x
            if ax > pk:
                pk = ax
        if pk > 0:
            g = self.TARGET_PEAK / float(pk)
            if g > self.GAIN_MAX:
                g = self.GAIN_MAX
            if abs(g - 1.0) > 0.01:
                samples = [int(x * g) for x in samples]

        # ★ 软限幅提升响度（见 SOFT_CLIP_DRIVE 注释）
        d = self.SOFT_CLIP_DRIVE
        if d > 1.001:
            lim = self.TARGET_PEAK
            out = []
            for x in samples:
                t = math.tanh(d * x / float(lim)) / math.tanh(d)
                v = int(t * lim)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                out.append(v)
            samples = out
'''
assert old_norm in src, "归一化锚点没找到"
src = src.replace(old_norm, new_norm, 1)
print("  OK: 归一化后加软限幅")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("audio_svc.py syntax OK")
print("  SOFT_CLIP_DRIVE = 2.2（可调）")
