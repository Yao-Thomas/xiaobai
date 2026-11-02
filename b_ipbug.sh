echo "=== apps_wifi.py 里的 IP 获取逻辑 ==="
grep -nE "hostname| 192\.168|192\.168|ip addr|ifconfig|inet|gw|gateway|def .*ip|SSID|ssid" /home/zynq/ui/apps_wifi.py | head -40
echo
echo "=== 文件大小和行数 ==="
wc -l /home/zynq/ui/apps_wifi.py
echo
echo "=== apps_net.py 里的（也可能有）==="
grep -nE "192\.168|ip addr|ifconfig|inet |hostname -I" /home/zynq/ui/apps_net.py | head -20
echo
echo "=== 全局搜硬编码的旧网段 ==="
sudo grep -rn "192\.168\.10\." /home/zynq/ui/ 2>/dev/null | head -20