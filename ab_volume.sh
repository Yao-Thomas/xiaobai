#!/bin/bash
# A/B 对放：原版 vs 放大版
echo "##############################################"
echo "#  A：原版（和 Codex 当时完全一样）"
echo "##############################################"
aplay -q /home/zynq/Music/03_小星星.wav
echo "  A 放完"
sleep 2
echo
echo "##############################################"
echo "#  B：放大版（RMS +15.7 dB，推力 5.0）"
echo "##############################################"
aplay -q /tmp/星星_最响.wav
echo "  B 放完"
echo
echo "=== 两版的实际数据 ==="
python3 - <<'PY'
import wave, struct, math
def st(p, tag):
    w = wave.open(p, "rb")
    n, r, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
    raw = w.readframes(n); w.close()
    v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
    rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
    pk = max(abs(x) for x in v)
    print("  %-14s 峰值=%5d (%5.1f dBFS)   RMS=%5.0f (%5.1f dBFS)"
          % (tag, pk, 20*math.log10(pk/32767.0), rms, 20*math.log10(rms/32767.0)))
st("/home/zynq/Music/03_小星星.wav", "A 原版")
st("/tmp/星星_最响.wav", "B 放大版")
PY
