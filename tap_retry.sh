#!/bin/bash
echo "  桌面进程: $(systemctl is-active zynq-desktop)  PID=$(systemctl show -p MainPID --value zynq-desktop)"
echo "  触摸设备权限: $(ls -l /dev/input/event1 | awk '{print $1, $3, $4}')"
sudo chmod 666 /dev/input/event1 2>/dev/null
echo "  重新点 Dock 上的音乐 (656, 552)"
sudo python3 /tmp/tap.py 656 552
sleep 1
echo "  再点一次 (656, 548)"
sudo python3 /tmp/tap.py 656 548
sleep 3
echo "  桌面还在吗: $(systemctl is-active zynq-desktop)"