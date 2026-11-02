#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot2.py —— 读板子 /dev/fb0 生成截图（不依赖硬编码 IP）。

用法: python shot2.py [输出png] [--page 0|1]
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board as B                                              # noqa: E402

W, H, STRIDE = 1024, 600, 3072


def grab(out="D:/ubuntu_iso/shot_now.png", page=0):
    off = page * H * STRIDE
    B.run("sudo dd if=/dev/fb0 of=/tmp/_shot.raw bs=%d count=%d skip=%d "
          "2>/dev/null; sudo chmod 644 /tmp/_shot.raw; ls -l /tmp/_shot.raw"
          % (STRIDE, H, page * H), quiet=False)
    c = B.conn()
    sftp = c.open_sftp()
    sftp.get("/tmp/_shot.raw", out + ".raw")
    sftp.close()
    c.close()
    try:
        from PIL import Image
    except ImportError:
        print("没有 PIL，原始数据在 %s.raw" % out)
        return out + ".raw"
    with open(out + ".raw", "rb") as f:
        data = f.read(W * H * 3)
    img = Image.frombytes("RGB", (W, H), data, "raw", "BGR")
    img.save(out)
    os.remove(out + ".raw")
    print("已保存 %s (%dx%d)" % (out, W, H))
    return out


if __name__ == "__main__":
    o = sys.argv[1] if len(sys.argv) > 1 else "D:/ubuntu_iso/shot_now.png"
    pg = 0
    if "--page" in sys.argv:
        pg = int(sys.argv[sys.argv.index("--page") + 1])
    grab(o, pg)
