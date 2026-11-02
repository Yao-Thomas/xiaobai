#!/usr/bin/env bash
# 播放前的静默准备：音量设满 + 检查时钟/寄存器状态（不出声）
echo "=== 1) I2S 两个核（确认这个新 bitstream 下状态）==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL, I2S_I2STIM
m=Mem()
print('  TX CORE_CTRL=%d  I2STIM=%d' % (m.rd(I2S_BASE,I2S_CORE_CTRL), m.rd(I2S_BASE,I2S_I2STIM)))
print('  RX CORE_CTRL=%d  I2STIM=%d' % (m.rd(I2S_RX_BASE,I2S_CORE_CTRL), m.rd(I2S_RX_BASE,I2S_I2STIM)))
m.close()
" 2>&1 | tail -3
echo
echo "=== 2) ES8388 关键寄存器 ==="
printf "  "
for r in 0x00 0x01 0x02 0x03 0x1a 0x1b 0x27 0x2a 0x2e 0x30; do
  printf "0x%s=%s " "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
echo
echo "=== 3) 音量（补回我撤掉的最大值）==="
amixer -c 0 -q sset 'Playback' 192 2>/dev/null
amixer -c 0 -q sset 'Output 1' 33 2>/dev/null
amixer -c 0 -q sset 'Output 2' 33 2>/dev/null
sleep 1
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 2' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 4) 把音量 drop-in 加回来（这次带上，开机自动设满）==="
sudo mkdir -p /etc/systemd/system/zynq-audio.service.d
sudo tee /etc/systemd/system/zynq-audio.service.d/volume-max.conf > /dev/null <<'EOF'
[Service]
ExecStartPre=/bin/sh -c 'amixer -c 0 -q sset "Playback" 192 2>/dev/null; amixer -c 0 -q sset "Output 1" 33 2>/dev/null; amixer -c 0 -q sset "Output 2" 33 2>/dev/null; true'
EOF
sudo systemctl daemon-reload
echo "  已写回 volume-max.conf"
echo
echo "=== 5) 服务状态 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 6) 音乐文件（确认归一化还在）==="
ls -l /home/zynq/Music/03_小星星.wav | awk '{print "  "$5" 字节  "$9}'
