echo "=== 1) home.py 里 wifi_ip 相关 ==="
grep -nE "wifi_ip|has_ip|flush_ip|ip_addr|apps_wifi" /home/zynq/ui/home.py | head -25
echo
echo "=== 2) 谁在设置 wifi_ip（全 ui 目录）==="
grep -rnE "wifi_ip" /home/zynq/ui/*.py | head -20
echo
echo "=== 3) has_ip() 的实现 ==="
sed -n '280,300p' /home/zynq/ui/apps_wifi.py
echo
echo "=== 4) flush_ip() 的实现 ==="
sed -n '78,100p' /home/zynq/ui/apps_wifi.py