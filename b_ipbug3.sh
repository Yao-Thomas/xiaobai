echo "=== run_dhcp() 全文 ==="
sed -n '92,140p' /home/zynq/ui/apps_wifi.py
echo
echo "=== iface() 怎么找网卡 ==="
grep -n "def iface" -A 20 /home/zynq/ui/apps_wifi.py | head -25
echo
echo "=== home.py 取 IP 的地方 (290-305) ==="
sed -n '290,305p' /home/zynq/ui/home.py