#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retry_sndcard.py —— 手动重新 bind xlnx_snd_card, 看是不是"启动时序"问题"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### 1) 声卡设备和驱动现在的绑定状态"
ls -l /sys/bus/platform/devices/xlnx_snd_card.0.auto/ 2>&1
echo "--- 驱动目录里有谁 ---"
ls /sys/bus/platform/drivers/xlnx_snd_card/ 2>&1
echo "--- device/driver 链接 ---"
ls -l /sys/bus/platform/devices/xlnx_snd_card.0.auto/driver 2>&1
echo
echo "### 2) i2s 收发器的绑定状态"
for d in 43c60000.i2s_receiver 43c70000.i2s_transmitter 43c50000.audio_formatter; do
  printf "%-28s driver=" $d
  ls -l /sys/bus/platform/devices/$d/driver 2>&1 | sed 's/.*-> //'
done
echo
echo "### 3) 试着 unbind + bind 声卡"
dmesg -c > /dev/null 2>&1
echo xlnx_snd_card.0.auto > /sys/bus/platform/drivers/xlnx_snd_card/unbind 2>&1
sleep 1
echo xlnx_snd_card.0.auto > /sys/bus/platform/drivers/xlnx_snd_card/bind 2>&1
echo "bind rc=$?"
sleep 2
echo "--- dmesg ---"
dmesg 2>&1 | grep -v AICWFDBG | head -20
echo
echo "### 4) 声卡出来了没"
cat /proc/asound/cards 2>&1
echo "--- aplay -l ---"
aplay -l 2>&1 | head -8
echo
echo "### 5) 如果还没有, 试着重新 bind i2s 收/发 + formatter, 再 bind 声卡"
for d in 43c70000.i2s_transmitter 43c60000.i2s_receiver 43c50000.audio_formatter; do
  drv=$(ls -l /sys/bus/platform/devices/$d/driver 2>/dev/null | sed 's/.*-> //' | xargs -r basename)
  echo "  $d -> $drv"
  [ -n "$drv" ] && echo $d > /sys/bus/platform/drivers/$drv/unbind 2>/dev/null
done
sleep 1
for d in 43c50000.audio_formatter 43c60000.i2s_receiver 43c70000.i2s_transmitter; do
  drv=$(ls -l /sys/bus/platform/devices/$d/driver 2>/dev/null | sed 's/.*-> //' | xargs -r basename)
  [ -n "$drv" ] && echo $d > /sys/bus/platform/drivers/$drv/bind 2>/dev/null
  echo "  rebind $d ($?)"
done
dmesg -c > /dev/null 2>&1
echo xlnx_snd_card.0.auto > /sys/bus/platform/drivers/xlnx_snd_card/bind 2>&1
sleep 2
echo "--- dmesg ---"; dmesg 2>&1 | grep -v AICWFDBG | head -25
echo "--- cards ---"; cat /proc/asound/cards 2>&1
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)


main()
