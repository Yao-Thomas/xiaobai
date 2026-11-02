#!/usr/bin/env bash
# 干净地测一遍音乐 App 的完整播放流程
echo "=== 0) 起始状态 ==="
echo -n "  状态文件: "; ls -l /tmp/zynq_music.json 2>/dev/null || echo "不存在"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 1) 点底部「应用」进应用页 ==="
sudo python3 /tmp/tap.py 378 550
sleep 2.5
echo
echo "=== 2) 点「音乐」图标 ==="
sudo python3 /tmp/tap.py 300 290
sleep 3
echo
echo "=== 3) 点第 7 行《03_小星星.wav》 ==="
sudo python3 /tmp/tap.py 400 358
sleep 1.5
echo
echo "=== 4) 播放中每 1.3 秒看状态 ==="
for i in $(seq 1 8); do
  printf "  t=%.1fs  " "$(awk "BEGIN{print $i*1.3}")"
  curl -s --max-time 5 http://127.0.0.1:8767/state
  echo
  sleep 1.3
done
echo
echo "=== 5) 状态文件（App 写给首页卡的）==="
cat /tmp/zynq_music.json 2>/dev/null && echo || echo "  还没有"
echo
echo "=== 6) aplay 还在跑吗 ==="
ps aux | grep "[a]play" | head -2
echo
echo "=== 7) 播完后 ==="
sleep 3
curl -s --max-time 5 http://127.0.0.1:8767/state; echo
cat /tmp/zynq_music.json 2>/dev/null && echo
