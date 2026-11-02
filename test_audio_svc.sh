#!/bin/bash
# 音频服务功能测试
B=http://127.0.0.1:8767
echo "=== 1) 免耳朵自检（放1kHz同时用麦克风录）==="
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' \
     -d '{"freq":1000,"secs":1.2}' $B/selftest; echo

echo
echo "=== 2) 录音 2 秒 -> /tmp/t_rec.wav ==="
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' \
     -d '{"secs":2,"rate":16000,"mono":true}' -o /tmp/t_rec.wav $B/record
ls -l /tmp/t_rec.wav
python3 - <<'PY'
import wave
try:
    w = wave.open("/tmp/t_rec.wav","rb")
    n=w.getnframes()
    print("  WAV: ch=%d width=%d rate=%d frames=%d 时长=%.2fs"
          % (w.getnchannels(), w.getsampwidth(), w.getframerate(), n,
             n/float(w.getframerate())))
    import struct
    d = w.readframes(n)
    v = struct.unpack("<%dh" % (len(d)//2), d)
    print("  样本: min=%d max=%d 非零比例=%.1f%%"
          % (min(v), max(v), 100.0*sum(1 for x in v if x)/len(v)))
except Exception as e:
    print("  解析失败:", e)
PY

echo
echo "=== 3) 音量 33 -> 18 ==="
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"v":33}' $B/volume; echo
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"v":18}' $B/volume; echo
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"v":30}' $B/volume; echo

echo
echo "=== 4) 放单音 0.8s ==="
curl -s --max-time 20 -X POST -H 'Content-Type: application/json' \
     -d '{"tone":880,"secs":0.8,"amp":0.5}' $B/play; echo

echo
echo "=== 5) 放 WAV 文件 ==="
curl -s --max-time 20 -X POST -H 'Content-Type: application/json' \
     -d '{"file":"/home/zynq/ui/../ui/audio_svc.py"}' $B/play; echo

echo
echo "=== 6) 最终状态 ==="
curl -s --max-time 8 $B/state; echo
