echo "=== 关掉 WiFi 省电 ==="
sudo iw dev wlx688fc92bd646 set power_save off 2>&1
echo -n "  现在的状态: "; iw dev wlx688fc92bd646 get power_save 2>&1
echo
echo "=== 关掉父 hub 的 USB 自动挂起 ==="
for d in /sys/bus/usb/devices/1-1 /sys/bus/usb/devices/1-1.2 /sys/bus/usb/devices/usb1; do
  if [ -w "$d/power/control" ]; then
    echo on | sudo tee "$d/power/control" >/dev/null 2>&1 && echo "  $d -> on"
  fi
done
echo
echo "=== 记录当前 carrier 计数（用于对比）==="
sudo journalctl -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier" | sed 's/^/  Lost carrier 累计: /'
date