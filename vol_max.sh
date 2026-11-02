#!/bin/bash
# 免费提升：把 Output1/2 从 27 拉到 33（+9 dB），纯混音器操作，不出声
echo "=== 改前 ==="
amixer -c 0 sget 'Output 1' 2>&1 | tail -2
amixer -c 0 sget 'Output 2' 2>&1 | tail -2
echo
echo "=== 拉到最大 33 ==="
amixer -c 0 -q sset 'Output 1' 33
amixer -c 0 -q sset 'Output 2' 33
echo
echo "=== 改后 ==="
amixer -c 0 sget 'Output 1' 2>&1 | tail -2
amixer -c 0 sget 'Output 2' 2>&1 | tail -2
echo
echo "=== 确认 DAC 数字音量（Playback 192 = 0dB 最大）==="
amixer -c 0 sget 'Playback' 2>&1 | tail -2
echo
echo "=== 顺手看一眼有没有别的增益项没拉满 ==="
for c in 'Left Mixer Left Bypass' 'Right Mixer Right Bypass' 'Left Channel' 'Right Channel'; do
  printf "  %-26s " "$c"
  amixer -c 0 sget "$c" 2>/dev/null | tail -1 | tr -d '\n'
  echo
done
