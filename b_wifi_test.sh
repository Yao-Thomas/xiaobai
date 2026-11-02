echo "=== 1) 重启 wifi 服务，验证修复生效 ==="
sudo systemctl restart wifi-connect.service
sleep 18
echo "  service: $(systemctl is-active wifi-connect.service)"
echo
echo "=== 2) 省电状态（应为 off）==="
iw dev wlx688fc92bd646 get power_save
echo
echo "=== 3) IP 状态 ==="
ip -4 addr show wlx688fc92bd646 | grep -E "inet |state"
hostname -I
echo
echo "=== 4) wpa 状态 ==="
sudo wpa_cli -i wlx688fc92bd646 status 2>/dev/null | grep -E "ssid=|wpa_state="
echo
echo "=== 5) 掉线计数（对比基线 40）==="
sudo journalctl -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier" | sed 's/^/  Lost carrier 累计: /'
date