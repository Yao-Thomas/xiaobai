echo "=== 1) desktop-watchdog.sh 全文 ==="
sudo cat /usr/local/bin/desktop-watchdog.sh
echo
echo "=== 2) desktop-watchdog.service / timer ==="
sudo cat /etc/systemd/system/desktop-watchdog.service 2>/dev/null
sudo cat /etc/systemd/system/desktop-watchdog.timer 2>/dev/null
echo
echo "=== 3) 心跳文件 ==="
ls -la /tmp/*heartbeat* /run/*heartbeat* /tmp/.desktop* 2>/dev/null
echo
echo "=== 4) 桌面代码里怎么写心跳 ==="
grep -nE "heartbeat|心跳|/tmp/\.|touch.*hb|hb_" /home/zynq/ui/desktop.py | head -15
echo
echo "=== 5) 看门狗最近的日志 ==="
sudo journalctl -u desktop-watchdog --no-pager -n 20 2>/dev/null | tail -15