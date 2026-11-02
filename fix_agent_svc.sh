#!/bin/bash
echo "=== 状态 ==="
systemctl status zynq-agent --no-pager -n 8 2>&1 | tail -12
echo
echo "=== 单元文件 ==="
cat /etc/systemd/system/zynq-agent.service
echo
echo "=== 尝试启动 ==="
sudo systemctl start zynq-agent
sleep 4
systemctl is-active zynq-agent
curl -s --max-time 8 http://127.0.0.1:8765/health; echo
echo
echo "=== 若失败看日志 ==="
sudo journalctl -u zynq-agent --no-pager -n 12 2>&1 | tail -12
