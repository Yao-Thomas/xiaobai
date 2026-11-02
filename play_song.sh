#!/bin/bash
echo "--- 播放 03_小星星.wav（音量 33 = 最大）---"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/03_小星星.wav"}' \
  http://127.0.0.1:8767/play
echo
echo "--- 等它放完（约 7~8 秒）---"
sleep 9
curl -s --max-time 10 http://127.0.0.1:8767/state; echo