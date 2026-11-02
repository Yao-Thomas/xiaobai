#!/bin/bash
sudo pkill -9 -f test_ui.py 2>/dev/null
sudo pkill -9 -f desktop.py 2>/dev/null
sleep 2
sudo rm -f /tmp/desktop.log
cd /home/zynq/ui
sudo nohup python3 -u desktop.py > /tmp/desktop.log 2>&1 &
sleep 10
echo "=== 桌面日志 ==="
sudo cat /tmp/desktop.log
echo ""
echo "=== 进程 ==="
pgrep -af desktop.py || echo "(没起来!)"
