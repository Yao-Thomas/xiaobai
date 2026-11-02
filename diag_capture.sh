#!/usr/bin/env bash
# 诊断采集通路：看抓到的样本到底是音频还是卡死的常量
echo "=== 抓 1 秒，打印前 40 个样本的原始值 ==="
rm -f /tmp/diag_cap.wav
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 1 /tmp/diag_cap.wav 2>/dev/null
python3 - <<'PY'
import wave, math, os
p = "/tmp/diag_cap.wav"
if not os.path.exists(p):
    print("  没录到"); raise SystemExit
w = wave.open(p, "rb")
n, r, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
raw = w.readframes(n); w.close()
print("  %d 帧 %.2f秒 %dHz %dch %dbit" % (n, n/float(r), r, ch, sw*8))
v = []
for i in range(len(raw)//3):
    x = int.from_bytes(raw[3*i:3*i+3], "little")
    if x & 0x800000: x -= 0x1000000
    v.append(x)
print("  前 40 个样本 (L,R 交错):")
for i in range(0, min(40, len(v)), 8):
    print("    " + " ".join("%9d" % x for x in v[i:i+8]))
# 统计
FULL = 8388607.0
mx = max(v); mn = min(v)
pk = max(abs(mx), abs(mn))
uniq = len(set(v))
print()
print("  max=%d  min=%d  峰值=%.0f%% 满量程" % (mx, mn, pk/FULL*100))
print("  不同取值个数 = %d  (若很小说明是常量/卡死)" % uniq)
# 是否只在几个值之间跳
from collections import Counter
c = Counter(v).most_common(6)
print("  最常见取值: %s" % ["%d(x%d)" % (k, n2) for k, n2 in c])
# 相邻差分
d = [abs(v[i+2]-v[i]) for i in range(0, min(len(v)-2, 20000), 2)]
print("  平均相邻差分 = %.0f  (若≈0 说明是直流/常量)" % (sum(d)/max(1,len(d))))
PY
echo
echo "=== 对照：把 Capture Digital 降下来再试 ==="
amixer -c 0 sget 'Capture Digital' 2>/dev/null | grep -E "Front Left"
amixer -c 0 -q sset 'Capture Digital' 100 2>/dev/null
rm -f /tmp/diag_cap2.wav
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 1 /tmp/diag_cap2.wav 2>/dev/null
python3 - <<'PY'
import wave, os
p = "/tmp/diag_cap2.wav"
if not os.path.exists(p): print("  没录到"); raise SystemExit
w = wave.open(p, "rb"); raw = w.readframes(w.getnframes()); w.close()
v = []
for i in range(len(raw)//3):
    x = int.from_bytes(raw[3*i:3*i+3], "little")
    if x & 0x800000: x -= 0x1000000
    v.append(x)
FULL = 8388607.0
pk = max(abs(x) for x in v)
print("  Capture Digital=100 后:  峰值=%.0f%%  不同取值=%d"
      % (pk/FULL*100, len(set(v))))
PY
