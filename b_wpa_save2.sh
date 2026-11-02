echo "=== 1) 完整配置文件（看 13A02 有没有 psk）==="
sudo cat /etc/wpa_supplicant/wpa_supplicant.conf
echo
echo "=== 2) 13A02 那条在内存里的详细参数 ==="
sudo wpa_cli -i wlx688fc92bd646 get_network 3 ssid 2>&1
echo -n "  psk: "; sudo wpa_cli -i wlx688fc92bd646 get_network 3 psk 2>&1
echo -n "  key_mgmt: "; sudo wpa_cli -i wlx688fc92bd646 get_network 3 key_mgmt 2>&1
echo -n "  priority: "; sudo wpa_cli -i wlx688fc92bd646 get_network 3 priority 2>&1
echo
echo "=== 3) 有没有 .bak 或别的配置文件在打架 ==="
sudo ls -la /etc/wpa_supplicant/
echo
echo "=== 4) 检查是不是有别的服务/脚本也写这个文件 ==="
sudo grep -rln "wpa_supplicant.conf" /etc/systemd/system/ /usr/local/bin/ /home/zynq/ui/*.py 2>/dev/null