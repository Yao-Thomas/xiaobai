#!/bin/bash
sudo pkill -9 -f test_ui.py 2>/dev/null
sudo pkill -9 -f desktop.py 2>/dev/null
sleep 2
sudo rm -f /tmp/ui.log
cd /home/zynq/ui
sudo nohup python3 -u test_ui.py > /tmp/ui.log 2>&1 &
sleep 12
echo "=== 前 12 秒日志 ==="
sudo cat /tmp/ui.log
echo ""
echo "=== 进程 ==="
pgrep -af test_ui.py || echo "(已结束)"
