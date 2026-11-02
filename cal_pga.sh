#!/usr/bin/env bash
# 静默标定采集 PGA：只录环境声，看哪一档不削顶
echo "=== 采集增益标定（只录音，不出声）==="
echo "  当前: Left/Right Channel = $(amixer -c 0 sget 'Left Channel' 2>/dev/null | grep -oE 'Capture [0-9]+' | head -1)"
echo
echo "  PGA档  增益      峰值(dBFS)   RMS(dBFS)   削顶率   判定"
echo "  " + "--------------------------------------------------------------------" 
for d in 0 2 4 6 8; do
  amixer -c 0 -q sset 'Left Channel' $d 2>/dev/null
  amixer -c 0 -q sset 'Right Channel' $d 2>/dev/null
  rm -f /tmp/pga_$d.wav
  arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 1 /tmp/pga_$d.wav 2>/dev/null
  python3 - "$d" <<'PY'
import wave, struct, math, sys, os
d = sys.argv[1]
p = "/tmp/pga_%s.wav" % d
if not os.path.exists(p) or os.path.getsize(p) < 1000:
    print("  %-6s (无数据)" % d); raise SystemExit
w = wave.open(p, "rb")
raw = w.readframes(w.getnframes()); w.close()
v = []
for i in range(len(raw)//3):
    x = int.from_bytes(raw[3*i:3*i+3], "little")
    if x & 0x800000: x -= 0x1000000
    v.append(x)
FULL = 8388607.0
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
pk = max(abs(x) for x in v)
clip = sum(1 for x in v if abs(x) >= FULL*0.995)/float(len(v))
db = {0:"0dB",2:"+6dB",4:"+12dB",6:"+18dB",8:"+24dB"}.get(int(d), "?")
verdict = "★削顶" if clip > 0.01 else ("可用" if rms > 1000 else "太小")
print("  %-6s %-9s %-11.1f %-11.1f %-8.1f%% %s"
      % (d, db, 20*math.log10(max(1e-9,pk)/FULL), 20*math.log10(max(1e-9,rms)/FULL),
         clip*100, verdict))
PY
done
echo
echo "=== 恢复一个合理的默认（先设 2 = +6dB）==="
amixer -c 0 -q sset 'Left Channel' 2
amixer -c 0 -q sset 'Right Channel' 2
amixer -c 0 sget 'Left Channel' 2>/dev/null | grep -E "Mono:" | head -1
