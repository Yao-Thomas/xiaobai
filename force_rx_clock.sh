#!/usr/bin/env bash
echo "=== 1) 空闲时 I2S 两个核 ==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL, I2S_I2STIM
m=Mem()
print('  TX CORE_CTRL=%d  I2STIM=%d' % (m.rd(I2S_BASE,I2S_CORE_CTRL), m.rd(I2S_BASE,I2S_I2STIM)))
print('  RX CORE_CTRL=%d  I2STIM=%d' % (m.rd(I2S_RX_BASE,I2S_CORE_CTRL), m.rd(I2S_RX_BASE,I2S_I2STIM)))
m.close()
" 2>&1 | tail -3
echo
echo "=== 2) 起一个后台播放，播放中看两个核 ==="
aplay -q /home/zynq/Music/提示音.wav &
sleep 0.3
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
m=Mem()
print('  播放中: TX=%d  RX=%d' % (m.rd(I2S_BASE,I2S_CORE_CTRL), m.rd(I2S_RX_BASE,I2S_CORE_CTRL)))
m.close()
" 2>&1 | tail -2
wait 2>/dev/null
echo
echo "########################################################"
echo "#  现在放一段 3 秒纯音，并【全程强制打开接收器时钟】"
echo "#  请仔细听：有没有声音？"
echo "########################################################"
aplay -q /home/zynq/Music/03_小星星.wav &
AP=$!
# 全程把 RX 拉起来
for i in $(seq 1 20); do
  sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_RX_BASE, I2S_CORE_CTRL, I2S_BASE
m=Mem()
m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 1)
m.wr(I2S_BASE, I2S_CORE_CTRL, 1)
m.close()
" 2>/dev/null
  sleep 0.35
done
wait $AP 2>/dev/null
echo "  放完了"
echo
echo "=== 3) 播放后两个核 ==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
m=Mem()
print('  TX=%d  RX=%d' % (m.rd(I2S_BASE,I2S_CORE_CTRL), m.rd(I2S_RX_BASE,I2S_CORE_CTRL)))
m.close()
" 2>&1 | tail -2
