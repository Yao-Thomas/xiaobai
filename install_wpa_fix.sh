#!/bin/bash
#=====================================================================
#  install_wpa_fix.sh —— 让 wpa_cli 套接字目录开机自动创建
#  背景: /var/run 是内存文件系统, 重启就没了
#        -> wpa_cli 报 Permission denied -> WiFi 选择器失效
#  做法: 改 wifi-connect.service, 在启动 wpa_supplicant 前先建目录
#=====================================================================
set -u

echo "=== [1] 备份原 service ==="
cp -n /etc/systemd/system/wifi-connect.service \
      /etc/systemd/system/wifi-connect.service.bak 2>/dev/null
echo "  已备份 -> wifi-connect.service.bak"

echo ""
echo "=== [2] 加一行 ExecStartPre 创建目录 ==="
cat > /etc/systemd/system/wifi-connect.service <<'UNIT'
[Unit]
Description=AIC8800 WiFi auto connect
After=systemd-networkd.service
Wants=systemd-networkd.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/sbin/modprobe aic8800_fdrv
ExecStartPre=/bin/mkdir -p /var/run/wpa_supplicant
ExecStartPre=/bin/chown root:netdev /var/run/wpa_supplicant
ExecStartPre=/bin/chmod 770 /var/run/wpa_supplicant
ExecStartPre=/bin/sleep 8
ExecStart=/usr/sbin/wpa_supplicant -B -i wlx688fc92bd646 -c /etc/wpa_supplicant/wpa_supplicant.conf
ExecStartPost=/bin/sleep 6

[Install]
WantedBy=multi-user.target
UNIT
echo "  已更新"

echo ""
echo "=== [3] 重载 + 重启验证 ==="
systemctl daemon-reload
systemctl restart wifi-connect
sleep 9
echo -n "  服务: "; systemctl is-active wifi-connect
echo -n "  套接字: "; ls /var/run/wpa_supplicant/ 2>&1
echo -n "  wpa_cli: "; wpa_cli -i wlx688fc92bd646 status 2>&1 | grep -E "^(ssid|wpa_state)=" | tr '\n' ' '
echo ""
echo -n "  IP: "; hostname -I

echo ""
echo "=== [4] 等网络恢复 ==="
sleep 6
echo -n "  最终 IP: "; hostname -I | awk '{print $1}'
echo DONE-WPA-FIX
