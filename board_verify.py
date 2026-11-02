#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_verify.py —— 真机自动验证: 逐个打开应用并截图
  利用之前加的"远程点击注入" (/tmp/ui_tap), 不需要人手点
用法: python board_verify.py
"""
import os, sys, time
import paramiko
import numpy as np
from PIL import Image

HOST, USER, PASS = "192.168.43.210", "zynq", "123456"
W, H, STRIDE = 1024, 600, 3072
OUT = r"D:\总文件夹\FPGA2026\真机截图"

# 10 个图标的中心坐标 (5 列 × 2 行)
APPS = [
    ("01_扫雷",     224, 163), ("02_计算器", 368, 163), ("03_画板",  512, 163),
    ("04_文件",     656, 163), ("05_图片",   800, 163),
    ("06_命令面板", 224, 315), ("07_GPU加速", 368, 315), ("08_系统信息", 512, 315),
    ("09_网络",     656, 315), ("10_关于",   800, 315),
]
BACK = (70, 30)          # 各应用的 "< 返回" 按钮


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=25,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd):
    i, o, e = c.exec_command(cmd)
    return o.read().decode(errors="replace") + e.read().decode(errors="replace")


def tap(c, x, y):
    run(c, "echo '%d,%d' | sudo tee /tmp/ui_tap >/dev/null" % (x, y))


def shot(c, path):
    run(c, "sudo dd if=/dev/fb0 of=/tmp/_s.raw bs=%d count=%d 2>/dev/null; "
           "sudo chmod 644 /tmp/_s.raw" % (STRIDE, H))
    sftp = c.open_sftp()
    sftp.get("/tmp/_s.raw", path + ".raw")
    sftp.close()
    raw = open(path + ".raw", "rb").read()
    os.remove(path + ".raw")
    if len(raw) < STRIDE * H:
        raw = raw + b"\x00" * (STRIDE * H - len(raw))
    a = np.frombuffer(raw, dtype=np.uint8)[:STRIDE * H].reshape(H, STRIDE)
    a = a[:, :W * 3].reshape(H, W, 3)[:, :, ::-1]
    Image.fromarray(a).save(path)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    c = conn()
    print("已连接板子")
    print("桌面服务:", run(c, "systemctl is-active zynq-desktop").strip())

    # 先回桌面
    tap(c, *BACK); time.sleep(1.0)
    p = shot(c, os.path.join(OUT, "00_桌面.png"))
    print("  [桌面] -> %s" % os.path.basename(p))

    for name, x, y in APPS:
        tap(c, x, y)
        time.sleep(2.2)                      # 等应用启动
        p = shot(c, os.path.join(OUT, name + ".png"))
        print("  [%s] -> %s" % (name, os.path.basename(p)))
        tap(c, *BACK)
        time.sleep(1.2)

    print("\n=== 桌面日志(最后 20 行) ===")
    print(run(c, "tail -20 /var/log/zynq-desktop.log"))
    c.close()
    print("截图目录:", OUT)


main()
