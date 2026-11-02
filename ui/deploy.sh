#!/bin/bash
# 部署新应用并重启桌面
pkill -9 -f "[d]esktop.py" 2>/dev/null
sleep 1
systemctl daemon-reload
systemctl start zynq-desktop.service
sleep 9
echo "--- 服务 ---"
systemctl is-active zynq-desktop.service
pgrep -af "[d]esktop.py" | head -2
echo ""
echo "--- 日志 ---"
tail -10 /var/log/zynq-desktop.log 2>/dev/null
echo ""
echo "--- 应用文件 ---"
ls -1 /home/zynq/ui/apps_*.py
