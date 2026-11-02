#!/bin/bash
sudo pkill -9 -f mines.py 2>/dev/null
sleep 2
sudo rm -f /tmp/mines.log
sudo sh -c 'echo 0 > /sys/class/graphics/fbcon/cursor_blink' 2>/dev/null
sudo setsid python3 /home/zynq/mines.py > /tmp/mines.log 2>&1 < /dev/null &
sleep 7
echo "--- 程序输出 ---"
sudo cat /tmp/mines.log
echo "--- 进程 ---"
pgrep -af mines.py || echo "(没起来!)"
