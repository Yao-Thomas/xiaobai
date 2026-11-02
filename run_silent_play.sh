#!/bin/bash
# 静默复现测试：DAC 数字静音下边"放"边录，看故障 B 会不会出现
# ★ 不出声（0x1A/0x1B = 0xC0 = -96dB）
echo "=== 前置检查 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  静音锁    : "; [ -f /etc/zynq-silent ] && echo 生效 || echo 无
echo "  （服务停着正好，测试要独占设备；而且这个测试本来就不出声）"
echo
cd /home/zynq/ui || exit 1
sudo python3 -u silent_play_test.py --cycles 24 --secs 0.4 2>&1 \
  | grep -vE "^\[dma\]|^\[fmt\]|^\[codec\]|^\[i2s\]" | tail -60
echo
echo "=== 结束后确认 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
sudo python3 -c "
import sys
sys.path.insert(0, '/home/zynq/ui')
from audio_pl import I2C
i = I2C()
print('  0x1A=0x%02X 0x1B=0x%02X  （0xC0 = 仍然是静音）'
      % (i.rd(0x1A), i.rd(0x1B)))
i.close()
" 2>&1 | tail -2
