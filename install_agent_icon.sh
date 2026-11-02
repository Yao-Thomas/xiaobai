#!/bin/bash
# 在板上执行：改 .desktop_pages 并重启桌面
set -e
cd /home/zynq/ui
sudo python3 /tmp/add_agent_icon.py
echo "--- 安装 ---"
sudo cp /home/zynq/.desktop_pages /home/zynq/.desktop_pages.$(date +%H%M%S).bak
sudo cp /tmp/_pages.json /home/zynq/.desktop_pages
sudo chown root:root /home/zynq/.desktop_pages
sudo chmod 644 /home/zynq/.desktop_pages
echo "--- 现在的内容 ---"
cat /home/zynq/.desktop_pages
echo
sudo systemctl restart zynq-desktop
sleep 9
systemctl is-active zynq-desktop
