#!/bin/bash
echo "=== 1) 音乐 App 调的是哪些接口 ==="
grep -nE "AUDIO_|/play|/stop|/volume|/state|/record|urllib|http|8767|PORT" /home/zynq/ui/apps_music.py | head -25
echo
echo "=== 2) audio_alsa_svc.py 提供的路由 ==="
sed -n '145,200p' /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== 3) 服务当前状态 ==="
curl -s --max-time 10 http://127.0.0.1:8767/state; echo
echo
echo "=== 4) 音乐目录 ==="
ls -l /home/zynq/Music/*.wav 2>/dev/null | awk '{print "  "$5"  "$9}'
echo
echo "=== 5) 首页音乐卡读的状态文件 ==="
ls -l /tmp/zynq_music.json 2>/dev/null && cat /tmp/zynq_music.json 2>/dev/null | head -c 300
echo
echo "=== 6) 手工测一次服务的 /play（不出声也行，只看返回值）==="
curl -s --max-time 20 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/03_小星星.wav"}' \
  http://127.0.0.1:8767/play 2>&1 | head -c 400
echo