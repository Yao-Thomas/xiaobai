#!/usr/bin/env bash
echo "############################################################"
echo "#  第 1 段：提示音（0.55 秒）"
echo "############################################################"
aplay -q /home/zynq/Music/提示音.wav
echo "  --- 第 1 段放完 ---"
sleep 1.5

echo
echo "############################################################"
echo "#  第 2 段：《小星星》（7.42 秒）—— 主要听这段"
echo "############################################################"
aplay -q /home/zynq/Music/03_小星星.wav &
AP=$!
sleep 0.8
echo "  播放中的状态："
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL, FMT_BASE, MM2S
m=Mem()
c=m.rd(FMT_BASE, MM2S+0x10)
print('    MM2S_CTRL = 0x%08X  位宽=%d DMA_EN=%d' % (c, (c>>16)&7, c&1))
print('    I2S TX=%d  RX=%d' % (m.rd(I2S_BASE,I2S_CORE_CTRL), m.rd(I2S_RX_BASE,I2S_CORE_CTRL)))
m.close()
" 2>&1 | tail -3
wait $AP 2>/dev/null
echo "  --- 第 2 段放完（aplay 退出码 $?）---"
echo
echo "############################################################"
echo "#  第 3 段：再放一次小星星（确认可重复）"
echo "############################################################"
aplay -q /home/zynq/Music/03_小星星.wav
echo "  --- 第 3 段放完 ---"
echo
echo "=== 播放后寄存器（看有没有被改小）==="
printf "  "
for r in 0x03 0x1a 0x1b 0x2e 0x30; do
  printf "0x%s=%s " "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
