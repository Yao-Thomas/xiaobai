#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_state.py —— 收尾自检: 板子回到我们的系统后是否一切正常 + 抓一张屏幕"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot
from PIL import Image

IP = "192.168.10.18"
RAW = r"D:\ubuntu_iso\histrial\fb0_ours.raw"
PNG = r"D:\ubuntu_iso\histrial\screen_ours_after.png"

CMD = (
    'echo "### 内核"; uname -v; '
    'echo "### 服务"; systemctl is-active zynq-desktop zynq-screen-guard wifi-connect ssh; '
    'echo "### 失败单元"; systemctl --failed --no-pager; '
    'echo "### PL 设备"; ls /sys/bus/platform/devices/ | grep -E "43c|412|416"; '
    'echo "### DRM"; for c in /sys/class/drm/card*/card*/status; do echo "$c = $(cat $c)"; done; '
    'echo "### /mnt/boot"; ls /mnt/boot/; '
    'echo "### 空间"; df -h / /mnt/boot'
)


def main():
    board.HOST = IP
    out, _ = broot.srun(CMD, timeout=90, quiet=True)
    print(out)

    broot.srun("dd if=/dev/fb0 of=/tmp/ours_fb.raw bs=1M count=2 2>/dev/null; "
               "chmod 644 /tmp/ours_fb.raw; ls -l /tmp/ours_fb.raw", quiet=True)
    board.get("/tmp/ours_fb.raw", RAW)
    d = open(RAW, "rb").read()
    Image.frombytes("RGB", (1024, 600), d[:3072 * 600], "raw", "BGR", 3072).save(PNG)
    print("截图 -> " + PNG)


main()
