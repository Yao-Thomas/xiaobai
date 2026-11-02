#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_delete2.py —— 更可靠的删除功能真机验证"""
import os, time
import paramiko
import numpy as np
from PIL import Image

HOST, USER, PASS = "192.168.43.210", "zynq", "123456"
W, H, STRIDE = 1024, 600, 3072
OUT = r"D:\总文件夹\FPGA2026\真机截图"
IMG_ICON = (800, 163)
DEL_BTN  = (931, 99)
OK_BTN   = (390, 343)
SCRATCH_X = 931              # 删除按钮的 x 坐标
# 注意: 本脚本只会删除自己创建的 __deltest__.png, 不会碰用户任何文件


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=25,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd):
    i, o, e = c.exec_command(cmd)
    return o.read().decode(errors="replace") + e.read().decode(errors="replace")


def tap(c, x, y, tag=""):
    run(c, "echo '%d,%d' | sudo tee /tmp/ui_tap >/dev/null" % (x, y))
    print("    注入点击 (%d,%d) %s" % (x, y, tag))


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
    a = a[:, :W * 3].reshape(H, W, 3)[:, :, ::-1]
    Image.fromarray(a).save(p)
    return p


def exists(c, p):
    return run(c, "test -f '%s' && echo YES || echo NO" % p).strip() == "YES"


def main():
    os.makedirs(OUT, exist_ok=True)
    c = conn()
    print("已连接板子")

    # ★ 安全: 只删【本脚本自己创建】的临时文件, 绝不碰用户的图片
    SCRATCH = "/home/zynq/Pictures/__deltest__.png"
    run(c, "python3 -c \"from PIL import Image; "
           "Image.new('RGB',(200,150),(200,80,80)).save('%s')\"" % SCRATCH)
    print("创建临时测试图: %s" % SCRATCH)
    print("删除前存在? %s" % exists(c, SCRATCH))

    # 记录用户图片(全程不动)
    user_imgs = run(c, "ls /home/zynq/Pictures/*.png 2>/dev/null | grep -v __deltest__").strip()
    print("你的图片(不会被碰):")
    for l in user_imgs.splitlines():
        print("   " + l)

    # 回桌面
    tap(c, 70, 30, "(返回)")
    time.sleep(1.5)

    # 打开图片应用
    tap(c, *IMG_ICON, "(图片图标)")
    time.sleep(3.0)
    p = shot(c, "X1_列表.png")
    print("  [1] 列表 -> %s" % os.path.basename(p))

    # 找到 __deltest__ 在第几行 (按字母序它排最前, 应是第 0 行)
    lines = [l for l in run(c, "ls /home/zynq/Pictures/*.png").split() if "__deltest__" in l]
    row = 0
    print("  临时图在第 %d 行" % row)

    tap(c, SCRATCH_X, 74 + row * 56 + 25, "(删除按钮)")
    time.sleep(2.0)
    p = shot(c, "X2_确认框.png")
    print("  [2] 确认框 -> %s" % os.path.basename(p))

    tap(c, *OK_BTN, "(确认删除)")
    time.sleep(2.5)
    p = shot(c, "X3_删除后.png")
    print("  [3] 删除后 -> %s" % os.path.basename(p))

    print("")
    still = exists(c, SCRATCH)
    print("临时图还在? %s" % still)
    print("你的图片还在? %s" % (run(c, "ls /home/zynq/Pictures/*.png | grep -v __deltest__ | wc -l").strip()))
    if not still:
        print(">>> ✅✅ 删除功能真机验证通过 (只删了临时图)")
    else:
        print(">>> ⚠️ 临时图还在")

    c.close()


main()
