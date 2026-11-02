echo "=== 网卡 ==="
ls /sys/class/net/ | tr '\n' ' '
echo
echo "=== IP ==="
hostname -I
echo "=== 无线 ==="
W=$(ls /sys/class/net | grep ^wl | head -1)
echo "  网卡: $W"
ip -4 addr show $W 2>/dev/null | grep inet
iw dev $W get power_save 2>&1
echo "=== wpa ==="
sudo wpa_cli -i $W status 2>/dev/null | grep -E "ssid=|wpa_state="
echo "=== 服务 ==="
systemctl is-active zynq-desktop zynq-agent zynq-audio
echo "=== 掉线计数 ==="
sudo journalctl -b -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier"