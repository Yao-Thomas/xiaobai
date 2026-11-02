echo "=== 1) USB 自动挂起（USB WiFi 掉线最常见原因）==="
cat /sys/module/usbcore/parameters/autosuspend 2>/dev/null
echo "--- 各 USB 设备的 power/control ---"
for d in /sys/bus/usb/devices/*/power/control; do
  [ -f "$d" ] && echo "  $d = $(cat $d 2>/dev/null)"
done | grep -B0 -A0 "" | head -20
echo
echo "=== 2) WiFi 省电模式 ==="
iw dev wlx688fc92bd646 get power_save 2>&1
echo
echo "=== 3) 网卡是否有 USB 省电设置 ==="
find /sys/bus/usb/devices/ -name "control" -path "*power*" 2>/dev/null | while read f; do
  dev=$(echo $f | cut -d/ -f6)
  echo "  $dev = $(cat $f 2>/dev/null)"
done
echo
echo "=== 4) 最近的掉线记录（次数）==="
sudo journalctl -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier"
echo "  ↑ Lost carrier 总次数"
sudo journalctl -u systemd-networkd --no-pager 2>/dev/null | grep -c "Gained carrier"
echo "  ↑ Gained carrier 总次数"
echo
echo "=== 5) dmesg 里有没有 USB 复位/断开 ==="
dmesg 2>/dev/null | grep -iE "usb.*(reset|disconnect|error|fail)" | tail -10