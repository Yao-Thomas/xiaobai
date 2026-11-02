#!/bin/bash
# 边放边录，用麦克风客观量实际声压（录音格式必须 S24_LE）
echo "=== 1) 先确认录音能开（S24_LE @ hw:0,1）==="
rm -f /tmp/cap_sil.wav
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 /tmp/cap_sil.wav 2>&1
echo "  退出码: $?  大小: $(stat -c%s /tmp/cap_sil.wav 2>/dev/null)"
echo
echo "=== 2) 边放（最响版）边录 ==="
aplay -q /tmp/星星_最响.wav &
AP=$!
sleep 1.2
rm -f /tmp/cap_play.wav
arecord -q -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 4 /tmp/cap_play.wav 2>&1
echo "  录音退出码: $?  大小: $(stat -c%s /tmp/cap_play.wav 2>/dev/null)"
wait $AP 2>/dev/null
echo "  aplay 退出码: $?"
echo
echo "=== 3) 对比电平 ==="
python3 - <<'PY'
import wave, struct, math, os

def stats(p, tag):
    if not os.path.exists(p) or os.path.getsize(p) < 1000:
        print("  %-10s ✗ 无数据" % tag); return None
    w = wave.open(p, "rb")
    n, r, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
    raw = w.readframes(n); w.close()
    if sw == 3:      # S24_LE, 有符号 24 位
        v = []
        for i in range(len(raw)//3):
            x = int.from_bytes(raw[3*i:3*i+3], "little")
            if x & 0x800000:
                x -= 0x1000000
            v.append(x)
    elif sw == 2:
        v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
    else:
        print("  %-10s 位宽 %d 暂不支持" % (tag, sw*8)); return None
    rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
    pk = max(abs(x) for x in v)
    full = 8388607.0 if sw == 3 else 32767.0
    print("  %-10s %.2f秒 %dHz %dch %dbit  RMS=%.0f (%.1f dBFS)  峰值=%.0f (%.1f dBFS)"
          % (tag, n/float(r), r, ch, sw*8, rms, 20*math.log10(max(1e-9,rms)/full),
             pk, 20*math.log10(max(1e-9,pk)/full)))
    return rms

a = stats("/tmp/cap_sil.wav", "静音基线")
b = stats("/tmp/cap_play.wav", "放音中")
if a and b and a > 0:
    print()
    print("  ★ 放音/基线 = %.1f 倍 = %+.1f dB" % (b/a, 20*math.log10(b/a)))
    if b > a * 3:
        print("     => 喇叭确实在出声")
    else:
        print("     => 几乎没差别，喇叭没怎么出声")
PY
