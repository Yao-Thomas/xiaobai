#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""save_default_wallpaper.py —— 生成桌面自带的渐变壁纸成 PNG

统一放到  /home/zynq/Pictures/wallpapers/  (桌面以 root 运行但能读这里)
"""
import os, sys
from PIL import Image, ImageDraw

W, H = 1024, 600
C_TOP = (30, 44, 86)
C_BOT = (7, 9, 20)
OUTDIR = "/home/zynq/Pictures/wallpapers"


def font(size, bold=False, cn=False):
    try:
        sys.path.insert(0, "/home/zynq/ui")
        from fbui import font as F
        return F(size, bold=bold, cn=cn)
    except Exception:
        return None


def glow(d, cx, cy, r, base, steps=26):
    for i in range(steps, 0, -1):
        t = i / float(steps)
        rr = int(r * t)
        c = tuple(int(base[j] * (1 - t) + C_BOT[j] * t) for j in range(3))
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=c)


def make():
    im = Image.new("RGB", (W, H), C_BOT)
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = (y / float(H)) ** 0.85
        d.line([(0, y), (W, y)],
               fill=(int(C_TOP[0] + (C_BOT[0] - C_TOP[0]) * t),
                     int(C_TOP[1] + (C_BOT[1] - C_TOP[1]) * t),
                     int(C_TOP[2] + (C_BOT[2] - C_TOP[2]) * t)))
    glow(d, 130, 90, 300, (52, 96, 190))
    glow(d, 950, 540, 300, (36, 78, 150))
    glow(d, 780, 120, 200, (90, 60, 160))
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=(24, 33, 58))
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(24, 33, 58))
    d.rectangle([820, 400, 1000, 560], outline=(60, 92, 150), width=3)
    d.rectangle([860, 440, 960, 520], outline=(60, 92, 150), width=2)
    for i in range(3):
        o = 840 + i * 40
        d.line([(o, 400), (o, 370)], fill=(60, 92, 150), width=3)
        d.line([(o, 560), (o, 590)], fill=(60, 92, 150), width=3)
    f1, f2 = font(30, bold=True), font(18, cn=True)
    if f1:
        d.text((52, 20), "Zynq-7020", font=f1, fill=(150, 185, 245))
    if f2:
        d.text((52, 56), "嵌入式小电脑", font=f2, fill=(120, 148, 200))
    return im


if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, "默认壁纸.png")
    make().save(out)
    os.chmod(out, 0o644)
    try:
        os.chown(out, 1000, 1000)
    except Exception:
        pass
    print("已生成: %s (%d 字节)" % (out, os.path.getsize(out)))
    print("目录内容:")
    for f in sorted(os.listdir(OUTDIR)):
        print("   %s" % f)
