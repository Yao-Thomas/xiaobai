#!/usr/bin/env bash
# 把新合成的《卡农》放到板上并播放
echo "=== 1) 上传 ==="
ls -l /home/zynq/卡农_响.wav 2>/dev/null && echo "  （已存在）"
echo
echo "=== 2) 确认真放了（文件信息）==="
python3 - <<'PY'
import wave, struct, math
p = "/home/zynq/卡农_响.wav"
w = wave.open(p, "rb")
n, sw, ch, r = w.getnframes(), w.getsampwidth(), w.getnchannels(), w.getframerate()
raw = w.readframes(n); w.close()
v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
pk = max(abs(x) for x in v)
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
print("  %dHz %dch %dbit  %.2f 秒" % (r, ch, sw*8, n/float(r)))
print("  RMS = %.1f dBFS   峰值 = %.1f dBFS"
      % (20*math.log10(max(1e-9,rms/32767.0)), 20*math.log10(max(1e-9,pk/32767.0))))
PY
echo
echo "=== 3) 放到音乐目录（播放器能扫到）==="
cp /home/zynq/卡农_响.wav "/home/zynq/Music/05_卡农.wav" 2>/dev/null && echo "  已放入 /home/zynq/Music/05_卡农.wav"
ls -l /home/zynq/Music/*.wav | awk '{print "  "$5"  "$9}'
echo
echo "=== 4) 确认增益全在顶 ==="
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
printf "  0x1D = "; sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null
echo
echo "############################################################"
echo "#  播放《卡农》（16 秒，RMS -10.1 dBFS）"
echo "#  对比：小星星在板上是 RMS 约 -11.0 dBFS"
echo "############################################################"
aplay -q "/home/zynq/Music/05_卡农.wav"
echo "  --- 放完 ---"
