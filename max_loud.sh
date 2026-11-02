#!/bin/bash
echo "=== 混音器实际值（完整输出）==="
for c in 'Playback' 'Output 1' 'Output 2'; do
  echo "--- $c ---"
  amixer -c 0 sget "$c" 2>&1
done
echo
echo "=== 服务记录的当前音量 ==="
curl -s --max-time 10 http://127.0.0.1:8767/state 2>/dev/null | head -c 300; echo
echo
echo "=== 播放最强版（推力5.0，RMS +15.7dB）==="
python3 - <<'PY'
import wave, struct, math, os
src = "/home/zynq/Music/03_小星星.wav"
w = wave.open(src, "rb")
ch, sw, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
raw = w.readframes(n); w.close()
v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
FULL = 32767.0
pk0 = max(abs(x) for x in v)
drive = 5.0
g1 = (0.95 * FULL) / pk0
xs = [x * g1 for x in v]
denom = math.tanh(drive)
ys = [math.tanh(drive * x / FULL) / denom for x in xs]
pk1 = max(abs(y) for y in ys)
g2 = (0.98) / pk1 if pk1 > 0 else 1.0
zs = [max(-32768, min(32767, int(y * FULL * g2))) for y in ys]
dst = "/tmp/星星_最响.wav"
w = wave.open(dst, "wb")
w.setnchannels(ch); w.setsampwidth(sw); w.setframerate(r)
w.writeframes(struct.pack("<%dh" % len(zs), *zs))
w.close()
r0 = math.sqrt(sum(float(a)*a for a in v)/len(v))
rz = math.sqrt(sum(float(a)*a for a in zs)/len(zs))
print("  原始 RMS=%.0f (%.1f dBFS)  新 RMS=%.0f (%.1f dBFS)  提升 %+.1f dB"
      % (r0, 20*math.log10(r0/FULL), rz, 20*math.log10(rz/FULL),
         20*math.log10(rz/r0)))
print("  已写", dst)
PY
echo
aplay -q /tmp/星星_最响.wav
echo "  aplay 退出码: $?"
