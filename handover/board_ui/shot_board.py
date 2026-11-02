#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_board.py —— 在板子上直接截图存成 PNG"""
import mmap, os, sys

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/shot.png"
fd = os.open("/dev/fb0", os.O_RDONLY)
mm = mmap.mmap(fd, 3072 * 600, mmap.MAP_SHARED, mmap.PROT_READ)
raw = mm[:]
mm.close()
os.close(fd)
try:
    from PIL import Image
    img = Image.frombytes("RGB", (1024, 600), raw, "raw", "BGR", 3072)
    img.save(out)
    print("已保存 %s  %s" % (out, img.size))
except Exception as e:
    print("PIL 失败: %s" % e)
    with open(out.replace(".png", ".raw"), "wb") as f:
        f.write(raw)
    print("已保存原始数据")
