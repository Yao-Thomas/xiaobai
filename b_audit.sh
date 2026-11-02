echo "########## 1) 全库搜硬编码的网段/IP/网卡名 ##########"
sudo grep -rnE "192\.168\.[0-9]+\.|10\.0\.|172\.16\.|wlan0" /home/zynq/ui/*.py 2>/dev/null | grep -v "^.*#" | head -30
echo
echo "########## 2) apps_wifi.py 里所有网络命令 ##########"
grep -nE "sh\(\"|sh\('|\"%s|ip -4|ip route|resolv|dns|gateway|networkctl|wpa_cli|iw " /home/zynq/ui/apps_wifi.py | head -35
echo
echo "########## 3) 有没有静态 IP 配置 ##########"
sudo ls -la /etc/systemd/network/
echo "--- 25-wlan.network ---"
sudo cat /etc/systemd/network/25-wlan.network
echo
echo "########## 4) DNS 配置 ##########"
cat /etc/resolv.conf 2>/dev/null | head -8
echo "--- resolved 状态 ---"
systemctl is-active systemd-resolved