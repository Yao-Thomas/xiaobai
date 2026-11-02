#!/bin/bash
#=====================================================================
#  fix_wpa_socket.sh —— 修好 wpa_cli 的控制套接字, 并验证扫描/连接能力
#=====================================================================
set -u

echo "=== [1] 创建控制套接字目录 ==="
mkdir -p /var/run/wpa_supplicant
chown root:netdev /var/run/wpa_supplicant 2>/dev/null
chmod 770 /var/run/wpa_supplicant
ls -ld /var/run/wpa_supplicant

echo ""
echo "=== [2] 重启 wifi-connect (让套接字建出来) ==="
systemctl restart wifi-connect
sleep 8
echo -n "  服务: "; systemctl is-active wifi-connect
echo -n "  IP: "; hostname -I | awk '{print $1}'

echo ""
echo "=== [3] 套接字建出来了吗 ==="
ls -la /var/run/wpa_supplicant/ 2>&1 | head -6

echo ""
echo "=== [4] ★ wpa_cli 能用吗 ==="
WLAN=$(ls /sys/class/net/ | grep -E '^wl' | head -1)
echo "  网卡: $WLAN"
echo "  --- status ---"
wpa_cli -i $WLAN status 2>&1 | head -10

echo ""
echo "=== [5] ★ 扫描测试 ==="
wpa_cli -i $WLAN scan >/dev/null 2>&1
sleep 4
echo "  --- scan_results (前12行) ---"
wpa_cli -i $WLAN scan_results 2>&1 | head -12

echo ""
echo "=== [6] iw 扫描 (备用方案测试) ==="
iw dev $WLAN scan 2>/dev/null | grep -E "SSID:|signal:" | head -16

echo ""
echo "=== [7] 桌面服务跑在什么用户下 ==="
grep -E "^User|^ExecStart=" /etc/systemd/system/zynq-desktop.service
echo -n "  当前用户 id: "; id
echo DONE-WPA-FIX
