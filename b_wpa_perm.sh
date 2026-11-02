echo "=== 1) zynq 用户在哪些组 ==="
id zynq
echo
echo "=== 2) ctrl_interface 目录权限 ==="
sudo ls -ld /var/run/wpa_supplicant
sudo ls -la /var/run/wpa_supplicant/
echo
echo "=== 3) 【关键】以 zynq 用户身份试 save_config（模拟 App 的路径）==="
echo "--- 不加 sudo ---"
su - zynq -c "wpa_cli -i wlx688fc92bd646 save_config" 2>&1 | head -5
echo "--- 加 sudo -n ---"
su - zynq -c "sudo -n wpa_cli -i wlx688fc92bd646 save_config" 2>&1 | head -5
echo
echo "=== 4) 以 zynq 用户试 list_networks ==="
su - zynq -c "wpa_cli -i wlx688fc92bd646 list_networks" 2>&1 | head -8
echo
echo "=== 5) 桌面服务跑在哪个用户 ==="
systemctl show zynq-desktop -p User -p Group 2>/dev/null