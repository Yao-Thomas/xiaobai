#!/bin/bash
echo "=== 播放 3 秒纯音（990Hz，音量 33 最大，amp 0.9 满量程）==="
echo "    请仔细听！"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"tone":990,"secs":3.0,"amp":0.9}' \
  http://127.0.0.1:8767/play; echo
echo
echo "=== 再放一次 5 秒（1507Hz，mic 最敏感的频段附近）==="
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"tone":1507,"secs":5.0,"amp":0.9}' \
  http://127.0.0.1:8767/play; echo
echo
curl -s --max-time 10 http://127.0.0.1:8767/state; echo