#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot.py —— 直接读板子显存, 生成屏幕截图(不用拍照!)
用法: python shot.py [输出文件]
"""
import sys, os, paramiko
from PIL import Image

HOST, USER, PASS = "192.168.43.210", "zynq", "123456"
W, H, STRIDE = 1024, 600, 3072      # 24bpp BGR

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "D:/ubuntu_iso/shot.png"
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20,
              look_for_keys=False, allow_agent=False)
    # 板子上把可见的那 600 行 dump 出来
    cmd = "sudo dd if=/dev/fb0 of=/tmp/_shot.raw bs=%d count=%d 2>/dev/null; sudo chmod 644 /tmp/_shot.raw; ls -l /tmp/_shot.raw" % (STRIDE, H)
    i, o, e = c.exec_command(cmd)
    print(o.read().decode().strip())
    sftp = c.open_sftp()
    sftp.get("/tmp/_shot.raw", out + ".raw")
    sftp.close()
    c.close()
    raw = open(out + ".raw", "rb").read()
    print("读到字节:", len(raw), "期望:", STRIDE * H)
    if len(raw) < STRIDE * H:
        print("!! 字节数不足, 屏幕可能没在正常显示")
        raw = raw + b"\x00" * (STRIDE * H - len(raw))
    try:
        import numpy as np
        a = np.frombuffer(raw, dtype=np.uint8)[:STRIDE * H].reshape(H, STRIDE)
        a = a[:, :W * 3].reshape(H, W, 3)[:, :, ::-1]      # BGR -> RGB
        im = Image.fromarray(a)
    except ImportError:
        # 没有 numpy 就用纯 python (慢一点)
        buf = bytearray(W * H * 3)
        for y in range(H):
            row = raw[y * STRIDE:y * STRIDE + W * 3]
            buf[y * W * 3:(y + 1) * W * 3] = bytes(
                b for i in range(0, len(row), 3) for b in (row[i + 2], row[i + 1], row[i]))
        im = Image.frombytes("RGB", (W, H), bytes(buf))
    im.save(out)
    os.remove(out + ".raw")
    print("[OK] 截图已保存:", out, im.size)

main()
