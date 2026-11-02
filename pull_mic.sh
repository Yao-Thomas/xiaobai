#!/bin/bash
cp /tmp/mic_chunks/c10_rms01372.wav /tmp/mic_evidence.wav 2>/dev/null
cp /tmp/mic_chunks/c16_rms01534.wav /tmp/mic_evidence2.wav 2>/dev/null
ls -l /tmp/mic_evidence*.wav
echo "--- 转成 44.1k 立体声 wav 方便电脑播放 ---"
python3 - <<'PY'
import wave, struct, sys, os
src = "/tmp/mic_evidence.wav"
dst = "/tmp/mic_play.wav"
w = wave.open(src, "rb")
n = w.getnframes(); d = w.readframes(n); r = w.getframerate(); ch = w.getnchannels()
print("  源: %d 帧  %d Hz  %d 声道" % (n, r, ch))
w.close()
o = wave.open(dst, "wb")
o.setnchannels(1); o.setsampwidth(2); o.setframerate(r)
o.writeframes(d)
o.close()
print("  已存 %s (%d 字节)" % (dst, os.path.getsize(dst)))
PY