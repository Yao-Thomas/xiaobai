#!/bin/bash
B=http://127.0.0.1:8767
sudo systemctl restart zynq-audio
sleep 5
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' -d '{"v":33}' $B/volume; echo
echo
echo "=== 播《小星星》（归一化后，整首 7.42 秒）==="
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/03_小星星.wav"}' $B/play; echo
sleep 9
curl -s --max-time 10 $B/state; echo