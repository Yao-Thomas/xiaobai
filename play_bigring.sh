#!/bin/bash
B=http://127.0.0.1:8767
echo "=== 音量 24（不到满档，先听着不吓人）==="
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' -d '{"v":24}' $B/volume; echo
echo
echo "=== 环大小确认 ==="
curl -s --max-time 10 $B/state | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  play_ring = %d 字节 = %.2f 秒' % (d['play_ring'], d['play_ring']/352800.0))
"
echo
echo "=== 播《小星星》（整首 7.42 秒）==="
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/03_小星星.wav"}' $B/play; echo
sleep 9
curl -s --max-time 10 $B/state; echo