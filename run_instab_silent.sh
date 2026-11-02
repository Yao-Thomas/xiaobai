#!/bin/bash
# 纯录音调查，不放音。音频服务停着正好（RawCap 独占）。
echo "=== 确认静音状态 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  静音锁    : "; [ -f /etc/zynq-silent ] && echo 生效 || echo 无
echo
echo "=== 跑调查（20 次，约 20 秒）==="
cd /home/zynq/ui
sudo python3 -u instability_silent.py --trials 20 2>&1 | grep -vE "^\[dma\]|^\[fmt\]|^\[codec\]|^\[i2s\]" | tail -50
echo
echo "=== 结束后确认仍然静音 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio