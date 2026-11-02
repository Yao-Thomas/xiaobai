#!/bin/bash
# 准备音乐目录 + 测试文件，重启桌面
set -e
sudo mkdir -p /home/zynq/Music
sudo chown zynq:zynq /home/zynq/Music

echo "=== 生成两个测试 WAV ==="
# 1) 1kHz 纯音 3 秒（用 python 直接写，避免依赖）
python3 - <<'PY'
import wave, struct, math
p = "/home/zynq/Music/01_纯音1kHz.wav"
fs, secs = 44100, 3.0
w = wave.open(p, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
n = int(fs*secs)
w.writeframes(b"".join(struct.pack("<h", int(12000*math.sin(2*math.pi*1000*i/fs)))
                       for i in range(n)))
w.close()
print("  写好", p)
PY

# 2) espeak 中文（离线 TTS）
if command -v espeak-ng >/dev/null; then
  espeak-ng -v cmn -s 150 -w /home/zynq/Music/02_语音测试.wav \
    "你好，我是系统管家小白。这段语音是板子上用离线引擎合成的。" 2>/dev/null || true
  ls -l /home/zynq/Music/02_语音测试.wav 2>/dev/null || true
fi

# 3) 用音频服务现录一段（验证"板载录音器"）
echo "=== 用板载麦克风录 3 秒 ==="
curl -s --max-time 120 -X POST -H 'Content-Type: application/json' \
  -d '{"secs":3,"rate":16000,"mono":true}' \
  -o /home/zynq/Music/03_板载录音.wav http://127.0.0.1:8767/record
python3 - <<'PY'
import wave
try:
    w = wave.open("/home/zynq/Music/03_板载录音.wav","rb")
    n = w.getnframes()
    print("  板载录音: ch=%d rate=%d frames=%d 时长=%.2fs"
          % (w.getnchannels(), w.getframerate(), n, n/float(w.getframerate())))
except Exception as e:
    print("  录音失败:", e)
PY

chown -R zynq:zynq /home/zynq/Music
echo "=== /home/zynq/Music ==="
ls -l /home/zynq/Music

echo "=== 重启桌面 ==="
sudo systemctl restart zynq-desktop
sleep 9
systemctl is-active zynq-desktop
