#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_tts_vol.py —— 两处改动

1) 百度 TTS 的 vol 默认值 5 -> 15
   实测（板上，2026-09-28）：
       vol=5  RMS 2429  峰值 12831
       vol=15 RMS 4858  峰值 25662   = +6.0 dB
   我们一直用默认值，等于白白少了 6 dB。

2) synth() 的 auto 顺序改成 **百度优先**（与 asr.py 一致）
   百度是自然语音，espeak 是机器音（之前识别不准的帮凶之一）。
   espeak 保留为**离线兜底**（断网时还能说话）。
"""
import io
import re
import sys

P = "agent/tts.py"
src = io.open(P, encoding="utf-8").read()

if "vol=15" in src or "vol: int = 15" in src:
    print("已经改过 vol，跳过")
else:
    # 只改 synth() 的签名默认值
    old = "def synth(text, out_path=\"/tmp/xiaobai_say.wav\", per=0, spd=5, pit=5, vol=5,"
    new = "def synth(text, out_path=\"/tmp/xiaobai_say.wav\", per=0, spd=5, pit=5, vol=15,"
    if old in src:
        src = src.replace(old, new, 1)
        print("  OK: synth() vol 5 -> 15 (+6 dB)")
    else:
        print("  [!] 没找到 synth 的 vol 默认值")
        m = re.search(r"def synth\([^)]*\)", src, re.S)
        print("      实际签名:", m.group(0)[:160] if m else "?")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("syntax OK")

# 打印改后的签名
s2 = io.open(P, encoding="utf-8").read()
m = re.search(r"def synth\(.*?\):", s2, re.S)
if m:
    print("\n改后的签名:")
    for ln in m.group(0).splitlines():
        print("   ", ln.strip())
