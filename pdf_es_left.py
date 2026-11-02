#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高倍放大 ES8388 左侧引脚，看清 MCLK/SCLK/LRCK/DSDIN 各自接的是哪根网"""
from PIL import Image

im = Image.open(r"D:\ubuntu_iso\_sch_p2.png")
S = im.size[0] / 842.0
# ES8388 左侧引脚区（PDF 点坐标）
box = (int(30 * S), int(390 * S), int(180 * S), int(455 * S))
c = im.crop(box)
c = c.resize((c.width * 5, c.height * 5), Image.LANCZOS)
c.save(r"D:\ubuntu_iso\_sch_es8388_left.png")
print("ES8388 左侧引脚 ->", c.size)
