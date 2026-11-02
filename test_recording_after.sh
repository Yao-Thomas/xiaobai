#!/usr/bin/env bash
# 验证预测：录音是否随 BCLK 修复一起好了（录音不出声）
echo "=== 1) 录 3 秒（16kHz 单声道，走 hw:0,1）==="
rm -f /tmp/rec_after.wav
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 3 /tmp/rec_after.wav 2>&1
echo "  退出码: $?  大小: $(stat -c%s /tmp/rec_after.wav 2>/dev/null)"
echo
echo "=== 2) 数据分析（关键：是不是还全零）==="
python3 - <<'PY'
import wave, struct, math, os
p = "/tmp/rec_after.wav"
if not os.path.exists(p) or os.path.getsize(p) < 1000:
    print("  ✗ 没录到"); raise SystemExit
w = wave.open(p, "rb")
n, r, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
raw = w.readframes(n); w.close()
if sw == 4:
    v = list(struct.unpack("<%di" % (len(raw)//4), raw))
    FULL = 2147483647.0
else:
    v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
    FULL = 32767.0
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
pk = max(abs(x) for x in v)
uniq = len(set(v))
print("  %d 帧 = %.2f 秒  %dHz %dch %dbit" % (n, n/float(r), r, ch, sw*8))
print("  不同取值 = %-8d  RMS = %-12.0f (%.1f dBFS)" % (uniq, rms, 20*math.log10(max(1e-9,rms/FULL))))
print("  峰值     = %-12d (%.1f dBFS)" % (pk, 20*math.log10(max(1e-9,pk/FULL))))
print()
if uniq <= 2:
    print("  ✗ 仍然全零/常量 —— 录音没随放音一起好")
elif rms < 100:
    print("  ○ 有数据但很小（可能只是环境很静）")
else:
    print("  ★★ 录到真实数据了！不同取值 %d 个，RMS %.0f" % (uniq, rms))
    print("     => 假设成立：录音全零也是同一个 BCLK/LRCK 不同源问题")
print()
print("  前 16 个样本：")
for i in range(0, min(16, len(v)), 8):
    print("    " + " ".join("%10d" % x for x in v[i:i+8]))
PY
