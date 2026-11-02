#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_ports.py —— 板子上能用哪些"连线"（UART / USB）"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### 串口设备"
ls -l /dev/ttyPS* /dev/ttyS* /dev/ttyACM* /dev/ttyUSB* 2>&1 | head -20
echo
echo "### 设备树里 uart 的状态"
for u in /proc/device-tree/amba/serial@e0000000 /proc/device-tree/amba/serial@e0001000; do
  echo -n "$(basename $u): status="; tr -d '\0' < $u/status 2>/dev/null; echo
done
echo
echo "### 内核 USB 相关"
zcat /proc/config.gz 2>/dev/null | grep -E "USB_ACM|USB_SERIAL|USB_NET_CDCETHER|USB_NET_RNDIS|CONFIG_PPP=" || \
  echo "(无 /proc/config.gz)"
echo
echo "### nodejs / python"
python3 -V
apt-cache policy nodejs 2>&1 | head -4
echo
echo "### USB 当前接了什么"
ls /sys/bus/usb/devices/ 2>&1 | head
for d in /sys/bus/usb/devices/*/product; do [ -f "$d" ] && echo "  $(cat $d)"; done 2>/dev/null
echo
echo "### GPIO/排针可用性(ATK模块口)"
ls /sys/class/gpio/ 2>&1 | head -5
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=180)


main()
