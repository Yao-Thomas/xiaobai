#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_delete.py —— 真机验证图片删除功能 (触摸注入 + 截图)"""
import os, time
import paramiko
import numpy as np
from PIL import Image

HOST, USER, PASS = "192.168.43.210", "zynq", "123456"
W, H, STRIDE = 1024, 600, 3072
OUT = r"D:\总文件夹\FPGA2026\真机截图"
IMG_ICON = (800, 163)          # 桌面第 1 行第 5 个 = 图片
DEL_BTN  = (931, 99)           # 列表第 1 行右侧"删"按钮
OK_BTN   = (390, 343)          # 确认框"删除"


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


def main():
    os.makedirs(OUT, exist_ok=True)
    c = conn()
    print("已连接板子")

    before = run(c, "ls /home/zynq/Pictures/*.png 2>/dev/null | wc -l").strip()
    print("删除前图片数: %s" % before)
    names = run(c, "ls /home/zynq/Pictures/ | head -3").strip().replace("\n", " | ")
    print("  前几个: %s" % names)

    # 回桌面 -> 打开图片应用
    tap(c, 70, 30); time.sleep(1.0)
    tap(c, *IMG_ICON); time.sleep(2.5)
    p = shot(c, "V1_图片列表_带删除按钮.png")
    print("  [1] 列表 -> %s" % os.path.basename(p))

    # 点第一行的"删"
    tap(c, *DEL_BTN); time.sleep(1.2)
    p = shot(c, "V2_删除确认框.png")
    print("  [2] 确认框 -> %s" % os.path.basename(p))

    # 确认删除
    tap(c, *OK_BTN); time.sleep(1.8)
    p = shot(c, "V3_删除后列表.png")
    print("  [3] 删除后 -> %s" % os.path.basename(p))

    after = run(c, "ls /home/zynq/Pictures/*.png 2>/dev/null | wc -l").strip()
    print("")
    print("删除后图片数: %s" % after)
    if before != after:
        print(">>> ✅ 删除功能生效! (%s -> %s)" % (before, after))
    else:
        print(">>> ⚠️ 数量没变, 需要检查")

    print("")
    print("=== 桌面日志 ===")
    print(run(c, "tail -8 /var/log/zynq-desktop.log"))
    c.close()


main()
