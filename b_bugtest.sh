echo "=== 记录起点 ==="
date +%T
sudo sh -c 'echo "### BUGTEST ###" >> /var/log/zynq-desktop.log'
echo "  桌面启动时间: $(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)"
echo
echo "=== 打开浏览器，然后什么都不做，等 35 秒 ==="
printf '545,555' | sudo tee /tmp/ui_tap >/dev/null; sync
sleep 35
echo
echo "=== 结果 ==="
echo "  桌面启动时间: $(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)"
echo "  现在:         $(date +%T)"
echo
echo "=== 看门狗日志 ==="
sudo journalctl -u desktop-watchdog --no-pager --since "-60s" 2>/dev/null | grep -E "心跳|ok|stalled" | tail -6
echo
echo "=== 屏幕 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/s6.raw >/dev/null 2>&1 && echo "  已截图"