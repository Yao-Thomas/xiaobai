#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_i2c.py —— 装 i2c-tools, 扫三条 I2C 总线, 看 WM8960 到底挂在哪"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### 装 i2c-tools"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq i2c-tools 2>&1 | tail -3
which i2cdetect
echo
echo "### 三条总线分别是谁"
for b in 0 1 2; do
  echo "--- i2c-$b ---"
  readlink -f /sys/bus/i2c/devices/i2c-$b 2>&1
  ls /sys/bus/i2c/devices/i2c-$b/name 2>/dev/null && cat /sys/bus/i2c/devices/i2c-$b/name
done
echo
echo "### 扫描"
for b in 0 1 2; do
  echo "===== i2cdetect -y -r $b ====="
  i2cdetect -y -r $b 2>&1
done
echo
echo "### 看看 PS I2C0 上 DT 声明的三个器件在不在"
for a in 0x50 0x51 0x1a; do
  printf "  i2c-1 addr %s : " $a
  i2cget -y 1 $a 0x00 2>&1 | head -1
done
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=600)


main()
