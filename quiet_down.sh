#!/bin/bash
B=http://127.0.0.1:8767
echo "=== 1) 立刻停 ==="
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' \
  -d '{}' $B/stop; echo
sleep 1
echo
echo "=== 2) 音量降到安全档（20 = -15dB，不是 33 满档了）==="
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' \
  -d '{"v":20}' $B/volume; echo
echo
echo "=== 3) 确认现在没在放 ==="
curl -s --max-time 10 $B/state; echo
