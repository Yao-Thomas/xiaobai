#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot3.py —— 用板上新的 shot_fb.py 抓正确的缓冲（替代 shot2.py）

shot2.py 固定读第 0 页，遇到双缓冲就会截到过期画面。
这个脚本调板上的 shot_fb.py（会查真实 yoffset），再取回来转 PNG。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board as B                                              # noqa: E402

W, H = 1024, 600


def grab(out="D:/ubuntu_iso/shot_now.png"):
    B.run("sudo python3 /home/zynq/ui/shot_fb.py /tmp/_shot.raw 2>&1; "
          "sudo chmod 644 /tmp/_shot.raw; ls -l /tmp/_shot.raw", quiet=False)
    c = B.conn()
    sftp = c.open_sftp()
    try:
        sftp.get("/tmp/_shot.raw", out + ".raw")
    finally:
        sftp.close()
        c.close()
    from PIL import Image
    with open(out + ".raw", "rb") as f:
        data = f.read(W * H * 3)
    if len(data) < W * H * 3:
        print("  ⚠ 数据不够: %d < %d" % (len(data), W * H * 3))
    img = Image.frombytes("RGB", (W, H), data[:W * H * 3], "raw", "BGR")
    img.save(out)
    os.remove(out + ".raw")
    print("已保存 %s (%dx%d)" % (out, W, H))
    return out


if __name__ == "__main__":
    o = sys.argv[1] if len(sys.argv) > 1 else "D:/ubuntu_iso/shot_now.png"
    grab(o)
