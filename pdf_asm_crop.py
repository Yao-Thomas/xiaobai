#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裁装配图：整板一眼 + 音频接口特写"""
import os

from PIL import Image

SRC = r"D:\ubuntu_iso\_asm_front_1.png"
im = Image.open(SRC)
W, H = im.size
S = W / 842.0
print("装配图", im.size, "缩放", S)

# 整板（整页）
im.save(r"D:\ubuntu_iso\_asm_full.png")
print("整板 -> _asm_full.png", im.size)

# 音频接口特写: PDF 点 (560,370)-(760,510)
box = (int(560 * S), int(370 * S), int(770 * S), int(510 * S))
c = im.crop(box)
c = c.resize((c.width * 3, c.height * 3), Image.LANCZOS)
c.save(r"D:\ubuntu_iso\_asm_audio_jacks.png")
print("音频接口特写 -> _asm_audio_jacks.png", c.size)

# 更宽一点，带周边丝印
box2 = (int(400 * S), int(300 * S), int(800 * S), int(560 * S))
c2 = im.crop(box2)
c2 = c2.resize((int(c2.width * 1.8), int(c2.height * 1.8)), Image.LANCZOS)
c2.save(r"D:\ubuntu_iso\_asm_audio_wide.png")
print("音频区较宽 -> _asm_audio_wide.png", c2.size)
