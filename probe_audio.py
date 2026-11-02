#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_audio.py —— P4 前置: 把音频链路的真实状态和 -517 的根因查清楚"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### 1) 声卡"
cat /proc/asound/cards 2>&1
echo "--- /dev/snd ---"; ls -l /dev/snd/ 2>&1
echo
echo "### 2) aplay / arecord 列表"
aplay -l 2>&1 | head -12
echo "---"
arecord -l 2>&1 | head -12
echo
echo "### 3) codec 节点有没有绑上驱动"
ls -l /sys/bus/i2c/devices/ 2>&1 | head -20
echo "--- i2c 0-001a (wm8960) ---"
ls -l /sys/bus/i2c/devices/0-001a/ 2>&1
echo "--- driver 链接 ---"
readlink -f /sys/bus/i2c/devices/0-001a/driver 2>&1
echo
echo "### 4) 平台设备绑定了没"
for d in /sys/bus/platform/devices/*43c*/ /sys/bus/platform/devices/xlnx*; do
  [ -e "$d" ] || continue
  n=$(basename $d)
  drv=$(readlink -f $d/driver 2>/dev/null | xargs -r basename)
  echo "$n -> ${drv:-（未绑定）}"
done
echo
echo "### 5) dmesg 里的音频相关（全量）"
dmesg | grep -iE "wm8960|asoc|snd|i2s|audio|codec|clk_wiz|pl_snd|formatter" 2>&1
echo
echo "### 6) clk_wiz 的时钟输出"
ls /sys/kernel/debug/clk/ 2>&1 | head -5
cat /sys/kernel/debug/clk/clk_summary 2>&1 | grep -iE "mclk|pclk|lcd|43c3" | head -20
echo
echo "### 7) 设备树里 wm8960 / audio_formatter 的实际内容"
for n in /proc/device-tree/amba/i2c@e0004000/wm8960@1a \
         /proc/device-tree/amba_pl/audio_formatter@43c50000 \
         /proc/device-tree/amba_pl/clk_wiz@43c30000 \
         /proc/device-tree/amba_pl/i2s_receiver@43c60000; do
  echo "=== $n"
  for f in $n/*; do
    [ -f "$f" ] || continue
    printf "   %-22s = " "$(basename $f)"
    tr '\0' ' ' < "$f" 2>/dev/null | head -c 200
    echo
  done
done
echo
echo "### 8) 有没有 i2c 工具 / 声卡工具"
for t in i2cdetect i2cget amixer alsamixer aplay arecord speaker-test; do
  printf "%-12s " $t; command -v $t || echo "(无)"
done
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)


main()
