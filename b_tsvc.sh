echo "=== 1) 装服务 ==="
sudo cp /tmp/thermal-guard.service /etc/systemd/system/thermal-guard.service
sudo systemctl daemon-reload
sudo systemctl enable thermal-guard 2>&1 | tail -2
sudo systemctl start thermal-guard
sleep 8
echo "  状态: $(systemctl is-active thermal-guard)  enabled=$(systemctl is-enabled thermal-guard)"
echo
echo "=== 2) 守护日志 ==="
sudo tail -6 /var/log/thermal_guard.log
echo
echo "=== 3) 状态文件 ==="
sudo python3 /home/zynq/thermal_guard.py --status
echo
echo "=== 4) ★ 温度趋势记录（后台记 60 秒）==="
sudo sh -c 'nohup sh -c "for i in \$(seq 1 20); do /usr/bin/python3 /home/zynq/thermal_guard.py --once | tr -d \"\\n\"; echo \" \$(cat /proc/loadavg | cut -d\" \" -f1)\"; sleep 3; done > /tmp/temptrend.txt 2>&1" >/dev/null 2>&1 &'
sleep 3
echo "  （已在后台记录，稍后读 /tmp/temptrend.txt）"