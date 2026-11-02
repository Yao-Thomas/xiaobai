#!/usr/bin/env bash
echo "=== 1) 桌面重启次数（按日志里的启动行统计）==="
sudo grep -a -c "桌面 v3 已启动" /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  累计启动次数: /'
echo "  最近 10 次启动的时间戳（用 journal 看）:"
sudo journalctl -u zynq-desktop --since "30 min ago" --no-pager 2>/dev/null | grep -a "Started\|Stopped\|Stopping" | tail -12 | sed 's/^/    /'
echo
echo "=== 2) 最近的 APP ERROR / Traceback（看是什么在崩）==="
sudo tail -200 /var/log/zynq-desktop.log 2>/dev/null | grep -a -B2 -A10 "APP ERROR\|Traceback" | tail -40 | sed 's/^/  /'
echo
echo "=== 3) 日志最后 25 行 ==="
sudo tail -25 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
echo
echo "=== 4) 日志文件大小与时间 ==="
sudo ls -l /var/log/zynq-desktop.log | sed 's/^/  /'
echo
echo "=== 5) 桌面当前进程 ==="
echo "  PID=$(systemctl show -p MainPID --value zynq-desktop)  状态=$(systemctl is-active zynq-desktop)"
