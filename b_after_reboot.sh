echo "=== 1) 开机多久 + 时间 ==="
uptime
date
echo
echo "=== 2) WiFi 自动连上了吗 ==="
sudo wpa_cli -i wlx688fc92bd646 status 2>/dev/null | grep -E "ssid=|wpa_state="
echo -n "  IP: "; hostname -I
echo
echo "=== 3) 省电模式（应为 off）==="
iw dev wlx688fc92bd646 get power_save 2>&1
echo
echo "=== 4) 掉线计数（重启后重新计数）==="
sudo journalctl -b -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier" | sed 's/^/  Lost carrier(本次开机): /'
sudo journalctl -b -u systemd-networkd --no-pager 2>/dev/null | grep -c "Gained carrier" | sed 's/^/  Gained carrier(本次开机): /'
echo
echo "=== 5) 配置文件里的网络（重启后还在吗）==="
sudo grep -E 'ssid=' /etc/wpa_supplicant/wpa_supplicant.conf
echo
echo "=== 6) 服务状态 ==="
for s in zynq-desktop zynq-audio zynq-agent wifi-connect; do printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"; done