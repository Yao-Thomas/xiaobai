#!/usr/bin/env bash
# 用 i2cset -f 改 ADC 寄存器（绕过 ALSA 驱动对 I2C 的占用）
# 验证：0x0A 从 0x50(LINE输入) 改成 0x00(麦克风) 能不能录到声音
echo "=== 当前 ADC 寄存器 ==="
for r in 0x03 0x0a 0x0d; do
  printf "  %s = %s\n" "$r" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
echo "=== A) 驱动原样，录 2 秒（对照）==="
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 /tmp/adc_A.wav 2>/dev/null
python3 -c "
import wave,struct,math
w=wave.open('/tmp/adc_A.wav','rb');n=w.getnframes();raw=w.readframes(n);w.close()
v=list(struct.unpack('<%di'%(len(raw)//4),raw))
rms=math.sqrt(sum(float(x)*x for x in v)/len(v))
print('  不同取值=%d  RMS=%.0f (%.1f dBFS)  峰值=%d'%(len(set(v)),rms,20*math.log10(max(1e-9,rms/2147483647.0)),max(abs(x) for x in v)))
"
echo
echo "=== B) 改成麦克风输入后录 4 秒（边录边纠正）==="
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 4 /tmp/adc_B.wav 2>/dev/null &
AP=$!
sleep 0.8
for k in $(seq 1 10); do
  sudo i2cset -f -y 1 0x10 0x03 0x51 2>/dev/null
  sudo i2cset -f -y 1 0x10 0x0a 0x00 2>/dev/null
  sudo i2cset -f -y 1 0x10 0x0d 0x02 2>/dev/null
  sleep 0.35
done
wait $AP 2>/dev/null
echo -n "  写入后: "
for r in 0x03 0x0a 0x0d; do printf "%s=%s  " "$r" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"; done
echo
python3 -c "
import wave,struct,math
w=wave.open('/tmp/adc_B.wav','rb');n=w.getnframes();raw=w.readframes(n);w.close()
v=list(struct.unpack('<%di'%(len(raw)//4),raw))
rms=math.sqrt(sum(float(x)*x for x in v)/len(v))
print('  不同取值=%d  RMS=%.0f (%.1f dBFS)  峰值=%d'%(len(set(v)),rms,20*math.log10(max(1e-9,rms/2147483647.0)),max(abs(x) for x in v)))
"
echo
echo "=== C) 只改 0x0A 一项（隔离变量）==="
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 3 /tmp/adc_C.wav 2>/dev/null &
AP=$!
sleep 0.7
for k in $(seq 1 8); do
  sudo i2cset -f -y 1 0x10 0x0a 0x00 2>/dev/null
  sleep 0.3
done
wait $AP 2>/dev/null
python3 -c "
import wave,struct,math
w=wave.open('/tmp/adc_C.wav','rb');n=w.getnframes();raw=w.readframes(n);w.close()
v=list(struct.unpack('<%di'%(len(raw)//4),raw))
rms=math.sqrt(sum(float(x)*x for x in v)/len(v))
print('  不同取值=%d  RMS=%.0f (%.1f dBFS)  峰值=%d'%(len(set(v)),rms,20*math.log10(max(1e-9,rms/2147483647.0)),max(abs(x) for x in v)))
"
echo
echo "=== D) 只改 0x03（偏置）==="
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 3 /tmp/adc_D.wav 2>/dev/null &
AP=$!
sleep 0.7
for k in $(seq 1 8); do
  sudo i2cset -f -y 1 0x10 0x03 0x51 2>/dev/null
  sleep 0.3
done
wait $AP 2>/dev/null
python3 -c "
import wave,struct,math
w=wave.open('/tmp/adc_D.wav','rb');n=w.getnframes();raw=w.readframes(n);w.close()
v=list(struct.unpack('<%di'%(len(raw)//4),raw))
rms=math.sqrt(sum(float(x)*x for x in v)/len(v))
print('  不同取值=%d  RMS=%.0f (%.1f dBFS)  峰值=%d'%(len(set(v)),rms,20*math.log10(max(1e-9,rms/2147483647.0)),max(abs(x) for x in v)))
"
echo
echo "=== 恢复驱动原值 ==="
sudo i2cset -f -y 1 0x10 0x03 0x09 2>/dev/null
sudo i2cset -f -y 1 0x10 0x0a 0x50 2>/dev/null
sudo i2cset -f -y 1 0x10 0x0d 0x03 2>/dev/null
for r in 0x03 0x0a 0x0d; do printf "  %s=%s\n" "$r" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"; done
