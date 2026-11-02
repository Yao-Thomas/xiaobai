#!/bin/bash
# ② 麦克风录音验证（走 ALSA，录音不出声）
echo "=== 1) 录音设备 ==="
arecord -l 2>&1 | head -8
echo
echo "=== 2) 采集设置 ==="
amixer -c 0 sget 'Left Channel' 2>&1 | tail -2
amixer -c 0 sget 'Right Channel' 2>&1 | tail -2
amixer -c 0 sget 'Capture Digital' 2>&1 | tail -2
amixer -c 0 sget 'Capture Mute' 2>&1 | tail -2
echo
echo "=== 3) 录 3 秒（16kHz 单声道）==="
rm -f /tmp/alsa_rec.wav
arecord -q -D hw:0,0 -f S16_LE -r 16000 -c 1 -d 3 /tmp/alsa_rec.wav 2>&1
echo "  退出码: $?"
ls -l /tmp/alsa_rec.wav 2>&1 | awk '{print "  "$5" 字节"}'
echo
echo "=== 4) 分析电平 ==="
python3 - <<'PY'
import wave, struct, math, os
p = "/tmp/alsa_rec.wav"
if not os.path.exists(p) or os.path.getsize(p) < 1000:
    print("  ✗ 没录到数据"); raise SystemExit
w = wave.open(p, "rb")
n, r, ch = w.getnframes(), w.getframerate(), w.getnchannels()
d = w.readframes(n); w.close()
v = struct.unpack("<%dh" % (len(d)//2), d)
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
pk = max(abs(x) for x in v)
nz = sum(1 for x in v if abs(x) > 16)/float(len(v))
print("  %d 帧 = %.2f 秒  %d Hz %d 声道" % (n, n/float(r), r, ch))
print("  RMS=%.0f  峰值=%d  非零%.0f%%" % (rms, pk, nz*100))
print("  %s" % ("★有信号" if rms > 50 else "⚠近乎静音（可能要说话才有）"))
PY
