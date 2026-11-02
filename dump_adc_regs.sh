#!/usr/bin/env bash
# 对比 ES8388 的 ADC 相关寄存器 vs 我老代码里"已知能录音"的那套
echo "=== 采集进行中，dump ES8388 寄存器 ==="
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 4 /tmp/regcap.wav 2>/dev/null &
AP=$!
sleep 1.0
echo "  reg   当前   已知能录音的值   说明"
echo "  ------------------------------------------------------------"
declare -A KNOWN=(
 [0x00]=0x06 [0x01]=0x50 [0x02]=0x00 [0x03]=0x51 [0x08]=0x00
 [0x09]=0x66 [0x0a]=0x00 [0x0b]=0x02 [0x0c]=0x00 [0x0d]=0x02
 [0x10]=0x00 [0x11]=0x00 [0x18]=0x03 [0x2b]=0x80
 [0x1a]=0x00 [0x1b]=0x00 [0x27]=0xf8 [0x2a]=0xf8
)
declare -A DESC=(
 [0x00]="芯片控制1" [0x01]="芯片控制2" [0x02]="芯片电源"
 [0x03]="★ADC电源" [0x08]="主模式" [0x09]="★ADC控制1/PGA"
 [0x0a]="★ADC控制2/LINPUT" [0x0b]="ADC控制3" [0x0c]="ADC控制4"
 [0x0d]="ADC控制5" [0x10]="ADC控制6" [0x11]="ADC控制7"
 [0x18]="ADC控制8" [0x2b]="DAC控制12" [0x1a]="DAC音量L"
 [0x1b]="DAC音量R" [0x27]="左混合器" [0x2a]="右混合器"
)
for r in 0x00 0x01 0x02 0x03 0x08 0x09 0x0a 0x0b 0x0c 0x0d 0x10 0x11 0x18 0x1a 0x1b 0x27 0x2a 0x2b; do
  cur=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  k=${KNOWN[$r]:-"--"}
  d=${DESC[$r]:-""}
  mark=""
  if [ "$k" != "--" ] && [ "$cur" != "$k" ]; then mark="  ★不一致"; fi
  printf "  %-6s %-7s %-15s %s%s\n" "$r" "$cur" "$k" "$d" "$mark"
done
wait $AP 2>/dev/null
echo
echo "=== 采集结果 ==="
python3 -c "
import wave, struct
w = wave.open('/tmp/regcap.wav','rb'); n=w.getnframes(); sw=w.getsampwidth()
raw=w.readframes(n); w.close()
if sw==4:
    v=list(struct.unpack('<%di'%(len(raw)//4), raw))
else:
    v=list(struct.unpack('<%dh'%(len(raw)//2), raw))
print('  %d 帧 位宽%d 不同取值=%d 峰值=%d' % (n, sw*8, len(set(v)), max(abs(x) for x in v)))
"
echo
echo "=== I2S RX 核状态 ==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
m=Mem()
print('  TX CORE_CTRL = %d' % m.rd(I2S_BASE, I2S_CORE_CTRL))
print('  RX CORE_CTRL = %d' % m.rd(I2S_RX_BASE, I2S_CORE_CTRL))
m.close()
" 2>&1 | tail -3
