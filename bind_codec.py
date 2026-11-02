#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bind_codec.py —— 清空 dmesg, 手动 bind wm8960, 看它到底为什么没起来"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### debugfs 状态"
mount | grep -i debug
ls -ld /sys/kernel/debug 2>&1
ls /sys/kernel/ 2>&1
echo
echo "### 清空 dmesg, 然后手动 bind"
dmesg -c > /dev/null 2>&1
echo "--- bind 结果 ---"
echo 1-001a > /sys/bus/i2c/drivers/wm8960/bind; echo "bind rc=$?"
sleep 2
echo "--- 驱动目录 (有设备就是绑上了) ---"
ls /sys/bus/i2c/drivers/wm8960/ 2>&1
echo "--- 设备目录有没有 driver 链接 ---"
ls -l /sys/bus/i2c/devices/1-001a/ 2>&1
echo
echo "### bind 之后的 dmesg (应该很干净)"
dmesg 2>&1 | grep -v AICWFDBG | head -40
echo
echo "### 声卡"
cat /proc/asound/cards 2>&1
echo
echo "### 再试 unbind/bind 一次, 看有没有 defer"
echo 1-001a > /sys/bus/i2c/drivers/wm8960/unbind 2>&1
dmesg -c > /dev/null 2>&1
echo 1-001a > /sys/bus/i2c/drivers/wm8960/bind 2>&1
sleep 2
dmesg 2>&1 | grep -v AICWFDBG | head -30
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)


main()
