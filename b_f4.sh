sleep 10
sudo python3 /home/zynq/ui/shot_fb.py /tmp/f4.raw >/dev/null 2>&1
echo "=== 桌面/浏览器状态 ==="
echo "  桌面启动: $(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)"
echo "  心跳年龄: $(($(date +%s) - $(cut -d. -f1 /run/desktop_beat 2>/dev/null))) 秒"
echo "  浏览器进程: $(pgrep -f 'desktop.py' | head -1)"
sudo journalctl -u desktop-watchdog --no-pager --since "-40s" 2>/dev/null | grep -E "心跳|ok|stalled" | tail -3