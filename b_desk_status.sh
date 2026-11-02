echo "=== 1) 桌面服务状态 ==="
systemctl status zynq-desktop --no-pager -l 2>&1 | head -14
echo
echo "=== 2) 重启了几次 ==="
systemctl show zynq-desktop -p NRestarts -p ExecMainStartTimestamp -p Restart 2>/dev/null
echo
echo "=== 3) 当前进程和启动时间 ==="
ps -eo pid,lstart,etime,args | grep desktop.py | grep -v grep
echo
echo "=== 4) 服务单元文件 ==="
cat /etc/systemd/system/zynq-desktop.service
echo
echo "=== 5) 日志里 "桌面 v3 已启动" 出现几次 + 时间戳 ==="
sudo journalctl -u zynq-desktop --no-pager -n 40 2>/dev/null | grep -cE "桌面 v3|Started|Stopped" 
sudo journalctl -u zynq-desktop --no-pager -n 20 2>/dev/null | tail -15