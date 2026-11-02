#!/usr/bin/env bash
echo "=== 播放前状态 ==="
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 点 03_小星星.wav（第7行）==="
sudo python3 /tmp/tap.py 400 393 2>&1
echo
echo "=== 播放中轮询服务状态 ==="
for i in 1 2 3 4 5 6; do
  sleep 1.2
  printf "  t=%4.1fs  " "$(echo "$i*1.2" | bc)"
  curl -s --max-time 5 http://127.0.0.1:8767/state
  echo
done
echo
echo "=== 播完后的首页音乐卡状态文件 ==="
cat /tmp/zynq_music.json 2>/dev/null || echo "  (还没有)"
echo
echo "=== Output 音量（确认没被改小）==="
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
