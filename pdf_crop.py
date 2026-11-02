#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裁剪原理图音频区域并放大，方便看清接线"""
import os
import sys

from PIL import Image

SRC = r"D:\ubuntu_iso\_sch_p2.png"
im = Image.open(SRC)
W, H = im.size           # 2526 x 1785  (= 842x595 pt @3x)
S = W / 842.0
print("页面", im.size, "缩放", S)

# 音频区域（PDF 点坐标）: x 25..575, y 385..555
box = (int(25 * S), int(385 * S), int(575 * S), int(555 * S))
crop = im.crop(box)
crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
out = r"D:\ubuntu_iso\_sch_audio.png"
crop.save(out)
print("裁出音频区 ->", out, crop.size)

# 再单独放大 ES8388 左边那一段（LOUT/ROUT 走线）
box2 = (int(140 * S), int(390 * S), int(420 * S), int(465 * S))
c2 = im.crop(box2)
c2 = c2.resize((c2.width * 3, c2.height * 3), Image.LANCZOS)
out2 = r"D:\ubuntu_iso\_sch_audio_out.png"
c2.save(out2)
print("裁出 LOUT/ROUT 段 ->", out2, c2.size)

# 喇叭那一段
box3 = (int(250 * S), int(420 * S), int(560 * S), int(555 * S))
c3 = im.crop(box3)
c3 = c3.resize((c3.width * 3, c3.height * 3), Image.LANCZOS)
out3 = r"D:\ubuntu_iso\_sch_audio_spk.png"
c3.save(out3)
print("裁出喇叭段 ->", out3, c3.size)
