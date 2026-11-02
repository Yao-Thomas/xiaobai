#!/bin/sh
# diag_net.sh —— 查"PC 连不上板子 8768"到底是什么问题
echo "======================================================"
echo " 网络诊断"
echo "======================================================"
echo
echo "【1】板子自己的网络"
hostname -I
echo "  --- 路由 ---"
ip route 2>/dev/null | head -5
echo "  --- WiFi 状态 ---"
iwconfig 2>/dev/null | grep -E "ESSID|Bit Rate|Quality|Signal" | head -4
echo
echo "【2】cloud-api 在跑吗"
systemctl is-active cloud-api
echo "  --- 监听端口 ---"
ss -tlnp 2>/dev/null | grep -E "8768|8769|8765" || netstat -tlnp 2>/dev/null | grep -E "8768|8769|8765"
echo
echo "【3】板子自己打自己"
curl -s --max-time 5 http://127.0.0.1:8768/health | head -c 90
echo
curl -s --max-time 5 "http://$(hostname -I | awk '{print $1}'):8768/health" | head -c 90
echo
echo
echo "【4】服务日志尾部"
tail -6 /var/log/cloud_api.log 2>/dev/null
echo
echo "【5】进程"
ps -ef | grep -E "cloud_api|cloud-api" | grep -v grep
echo
echo "【6】防火墙"
sudo iptables -L -n 2>/dev/null | head -8 || echo "  (没有 iptables)"
echo
echo "【7】温度"
sudo python3 /home/zynq/thermal_guard.py --once
