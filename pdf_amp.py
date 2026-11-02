#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高倍放大 MD8002A 功放那一小块，确认 SHUTDOWN 脚接哪"""
from PIL import Image

im = Image.open(r"D:\ubuntu_iso\_sch_p2.png")
S = im.size[0] / 842.0
print("缩放", S)

# U24 / MD8002A 区域
box = (int(320 * S), int(455 * S), int(560 * S), int(550 * S))
c = im.crop(box)
c = c.resize((c.width * 4, c.height * 4), Image.LANCZOS)
c.save(r"D:\ubuntu_iso\_sch_amp.png")
print("功放区 ->", c.size)

# 左半边：SPK_IN / R38 R39 / SHUTDOWN 入口
box2 = (int(320 * S), int(465 * S), int(450 * S), int(545 * S))
c2 = im.crop(box2)
c2 = c2.resize((c2.width * 6, c2.height * 6), Image.LANCZOS)
c2.save(r"D:\ubuntu_iso\_sch_amp_left.png")
print("功放左半 ->", c2.size)
