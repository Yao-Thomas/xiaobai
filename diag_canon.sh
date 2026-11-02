#!/usr/bin/env bash
# 诊断为什么《卡农》没出声
echo "=== 1) 文件到底在哪、叫什么 ==="
ls -lb /home/zynq/Music/ | grep -i canon
ls -lb /home/zynq/Music/*.wav | tail -4
echo
echo "=== 2) 用 ASCII 名字复制一份（排除中文名问题）==="
cp "/home/zynq/Music/05_卡农.wav" /home/zynq/Music/05_canon.wav 2>&1 && echo "  已复制为 05_canon.wav"
ls -l /home/zynq/Music/05_canon.wav
echo
echo "=== 3) 直接播 ASCII 名字版，【不加 -q】看有没有报错 ==="
aplay /home/zynq/Music/05_canon.wav
echo "  aplay 退出码: $?"
echo
echo "=== 4) 对照：播小星星（确认链路还在）==="
aplay /home/zynq/Music/03_小星星.wav 2>&1 | tail -3
echo "  aplay 退出码: $?"
echo
echo "=== 5) 文件头信息（确认不是坏文件）==="
file /home/zynq/Music/05_canon.wav
python3 -c "
import wave
w = wave.open('/home/zynq/Music/05_canon.wav','rb')
print('  ch=%d sw=%d rate=%d frames=%d' % (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()))
w.close()
"
echo
echo "=== 6) 设备状态 ==="
cat /proc/asound/cards | head -2
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 7) 有没有别的进程占着声卡 ==="
fuser -v /dev/snd/* 2>&1 | head -8
