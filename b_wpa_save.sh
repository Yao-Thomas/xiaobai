echo "=== 1) 配置文件里现在有哪些网络 ==="
sudo grep -E "^network=|ssid=" /etc/wpa_supplicant/wpa_supplicant.conf
echo
echo "=== 2) 内存里有哪些（wpa_cli）==="
sudo wpa_cli -i wlx688fc92bd646 list_networks 2>/dev/null
echo
echo "=== 3) 配置文件权限 + update_config 标志 ==="
ls -la /etc/wpa_supplicant/wpa_supplicant.conf
sudo grep -E "update_config|ctrl_interface" /etc/wpa_supplicant/wpa_supplicant.conf
echo
echo "=== 4) wpa_supplicant 进程参数（看是不是 root 跑的）==="
ps -eo user,pid,args | grep -E "wpa_supplicant" | grep -v grep
echo
echo "=== 5) 手动试一次 save_config ==="
sudo wpa_cli -i wlx688fc92bd646 save_config 2>&1
echo "  --- 存完之后配置文件里有什么 ---"
sudo grep -E "^network=|ssid=" /etc/wpa_supplicant/wpa_supplicant.conf