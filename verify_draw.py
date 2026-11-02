#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_draw.py —— 真机验证画板"笔画不连线"修复
做法:
  1. 注入第一笔拖拽 (左上区域)
  2. 注入第二笔拖拽 (右下区域)
  3. 截图画板
  4. 检查两笔之间的连线上有没有颜色 -> 有 = bug 还在
"""
import os, time
import paramiko
import numpy as np
from PIL import Image

HOST, USER, PASS = "192.168.43.210", "zynq", "123456"
W, H, STRIDE = 1024, 600, 3072
OUT = r"D:\总文件夹\FPGA2026\真机截图"

DRAW_ICON = (512, 163)          # 桌面第 1 行第 3 个 = 画板
CANVAS = (52, 68, 972, 504)

# 第一笔: 左上角画一条线; 第二笔: 右下角画一条线 (两笔离得很远)
STROKE1 = "drag:150,150;200,200;250,160;300,220"
STROKE2 = "drag:650,380;700,420;750,370;800,430"


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=25,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd):
    i, o, e = c.exec_command(cmd)
    return o.read().decode(errors="replace") + e.read().decode(errors="replace")


def inject(c, payload):
    run(c, "printf '%s' '%s' | sudo tee /tmp/ui_tap >/dev/null" % (payload, payload))


def shot(c, name):
    run(c, "sudo dd if=/dev/fb0 of=/tmp/_s.raw bs=%d count=%d 2>/dev/null; "
           "sudo chmod 644 /tmp/_s.raw" % (STRIDE, H))
    p = os.path.join(OUT, name)
    sftp = c.open_sftp()
    sftp.get("/tmp/_s.raw", p + ".raw")
    sftp.close()
    raw = open(p + ".raw", "rb").read()
    os.remove(p + ".raw")
    if len(raw) < STRIDE * H:
        raw += b"\x00" * (STRIDE * H - len(raw))
    a = np.frombuffer(raw, dtype=np.uint8)[:STRIDE * H].reshape(H, STRIDE)
    a = a[:, :W * 3].reshape(H, W, 3).copy()      # BGR
    bgr = a
    rgb = a[:, :, ::-1]
    Image.fromarray(rgb).save(p)
    return p, bgr


def main():
    os.makedirs(OUT, exist_ok=True)
    c = conn()
    print("已连接板子")

    # 回桌面 -> 打开画板
    inject(c, "70,30"); time.sleep(1.2)
    inject(c, "%d,%d" % DRAW_ICON); time.sleep(3.0)
    print("已打开画板")

    # 注入两笔
    print("注入第 1 笔:", STROKE1)
    inject(c, STROKE1); time.sleep(2.5)
    print("注入第 2 笔:", STROKE2)
    inject(c, STROKE2); time.sleep(2.5)

    p, bgr = shot(c, "D1_画板_两笔.png")
    print("截图 -> %s" % os.path.basename(p))

    # ---- 检查两笔之间有没有连线 ----
    # 第1笔终点约 (300,220), 第2笔起点约 (650,380) (画布坐标)
    x0, y0 = CANVAS[0] + 300, CANVAS[1] + 220
    x1, y1 = CANVAS[0] + 650, CANVAS[1] + 380
    n = 60
    hits = 0
    for i in range(1, n):
        t = i / float(n)
        x = int(x0 + (x1 - x0) * t)
        y = int(y0 + (y1 - y0) * t)
        px = bgr[y, x]                    # BGR
        # 画布底色是 (252,252,255) 附近; 笔画是深色(默认黑)
        if not (px[0] > 230 and px[1] > 230 and px[2] > 230):
            hits += 1
    print("")
    print("两笔之间连线上的非背景像素: %d / %d" % (hits, n - 1))
    if hits <= 2:
        print(">>> ✅✅ 没有连线! 画板修复真机验证通过")
    else:
        print(">>> ❌ 疑似还有连线, 需要检查")

    print("")
    print("=== 画板日志 ===")
    print(run(c, "tail -6 /var/log/zynq-desktop.log"))
    c.close()


main()
