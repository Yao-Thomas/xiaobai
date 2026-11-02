echo "=== 网络状态 ==="
ip -4 addr show wlx688fc92bd646 2>/dev/null | grep -E "inet "
echo -n "  hostname -I: "; hostname -I
echo
sudo wpa_cli -i wlx688fc92bd646 status 2>/dev/null | grep -E "ssid=|wpa_state="
echo
echo "=== 省电 ==="
iw dev wlx688fc92bd646 get power_save 2>&1
echo
echo "=== 掉线计数 ==="
sudo journalctl -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier" | sed 's/^/  Lost carrier: /'
sudo journalctl -u systemd-networkd --no-pager 2>/dev/null | grep -c "Gained carrier" | sed 's/^/  Gained carrier: /'
date