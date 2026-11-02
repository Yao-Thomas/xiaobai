echo "########## apps_settings.py 260-275 ##########"
sed -n '255,278p' /home/zynq/ui/apps_settings.py
echo
echo "########## apps_net.py 1-40 ##########"
sed -n '1,40p' /home/zynq/ui/apps_net.py
echo
echo "########## apps_net.py 里所有 wlan/ip 相关 ##########"
grep -nE "wlan|wlx|iface|ip -4|hostname -I|inet" /home/zynq/ui/apps_net.py | head -20
echo
echo "########## /etc/resolv.conf 是不是软链 ##########"
ls -la /etc/resolv.conf