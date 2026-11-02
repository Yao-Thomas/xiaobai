#!/bin/bash
echo "=== Output 混音器的量程 ==="
amixer -c 0 scontrols 2>&1 | head -20
echo
echo "--- Output 1 ---"
amixer -c 0 sget 'Output 1' 2>&1
echo
echo "--- Output 2 ---"
amixer -c 0 sget 'Output 2' 2>&1
echo
echo "=== formatter 当前 MM2S_CTRL ==="
sudo python3 -c "
import mmap, os, struct
# 用 devmem 更简单
" 2>/dev/null
sudo devmem 0x43C50110 32 2>/dev/null || echo "  (devmem 不可用)"
echo
echo "=== 播放时 formatter 会变成什么（Codex 记录: 0x00142001）==="
echo "  参考: 位宽字段 bit[18:16], 0x00142001 -> 位宽=4(32bit) DMA_EN=1"
echo
echo "=== audio_alsa_svc.py 的能力 ==="
grep -nE "def |/play|aplay|amixer|PAUSE|route" /home/zynq/ui/audio_alsa_svc.py | head -30