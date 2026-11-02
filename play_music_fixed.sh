#!/bin/bash
# 部署流式播放修复，然后用**音乐**（不是纯音）试听
B=http://127.0.0.1:8767

echo "=== 1) 重启音频服务（加载修复）==="
sudo systemctl restart zynq-audio
sleep 5
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo

echo "=== 2) 音量设成安全档 20 (-15dB)，不用 33 ==="
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' \
  -d '{"v":20}' $B/volume; echo
echo

echo "=== 3) 播《小星星》（整首 7.42 秒，不是前 0.186 秒了）==="
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/03_小星星.wav"}' $B/play; echo
echo
echo "  （等它放完）"
sleep 9
curl -s --max-time 10 $B/state; echo
