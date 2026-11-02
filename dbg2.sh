#!/bin/bash
echo "=== [A] 测试 sudo+setsid+重定向 能否写日志 ==="
sudo rm -f /tmp/t.log
sudo setsid python3 -u -c 'print("HELLO_FROM_PYTHON")' > /tmp/t.log 2>&1 < /dev/null
sleep 1
echo -n "日志内容: "; sudo cat /tmp/t.log

echo ""
echo "=== [B] 用 nohup 方式重跑扫雷 ==="
sudo pkill -9 -f mines.py 2>/dev/null
sleep 2
sudo rm -f /tmp/mines.log
sudo nohup python3 -u /home/zynq/mines.py > /tmp/mines.log 2>&1 &
sleep 8
echo -n "扫雷日志:["; sudo cat /tmp/mines.log; echo "]"
echo "进程: $(pgrep -c -f mines.py)"

echo ""
echo "=== [C] 看进程在等什么 ==="
for p in $(pgrep -f mines.py); do
  echo "--- PID $p ---"
  sudo cat /proc/$p/status 2>/dev/null | grep -E "^(Name|State)"
  sudo cat /proc/$p/wchan 2>/dev/null; echo ""
done
