#!/bin/bash
echo "=== 安装 espeak-ng (离线 TTS) ==="
sudo apt-get install -y --no-install-recommends espeak-ng 2>&1 | tail -8
echo
echo "=== 版本 / 中文语音 ==="
which espeak-ng && espeak-ng --version 2>&1 | head -2
echo "--- 可用普通话语音 ---"
espeak-ng --voices=zh 2>&1 | head -5
echo
echo "=== 合成中文 WAV 并播放 ==="
cd /tmp
if espeak-ng -v cmn -s 160 -w /tmp/es_test.wav "你好，我是系统管家小白，这块板子的系统管家。" 2>&1; then
  ls -l /tmp/es_test.wav
  python3 - <<'PY'
import wave
w = wave.open("/tmp/es_test.wav","rb")
print("  WAV: ch=%d width=%d rate=%d frames=%d 时长=%.2fs"
      % (w.getnchannels(), w.getsampwidth(), w.getframerate(),
         w.getnframes(), w.getnframes()/float(w.getframerate())))
PY
  echo "--- 交给音频服务播放 ---"
  curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
    -d '{"file":"/tmp/es_test.wav"}' http://127.0.0.1:8767/play
  echo
else
  echo "espeak-ng 合成失败"
fi
