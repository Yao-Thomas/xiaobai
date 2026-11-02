echo "=== 1) 立即状态 ==="
date
echo "  温度: $(sudo python3 /home/zynq/thermal_guard.py --once 2>/dev/null) °C"
uptime
echo
echo "=== 2) XADC 原始值（确认读数没漂）==="
cat /sys/bus/iio/devices/iio:device0/in_temp0_raw
echo "  scale=$(cat /sys/bus/iio/devices/iio:device0/in_temp0_scale)"
echo "  offset=$(cat /sys/bus/iio/devices/iio:device0/in_temp0_offset)"
echo
echo "=== 3) 守护状态 ==="
systemctl is-active thermal-guard
sudo python3 /home/zynq/thermal_guard.py --status
echo
echo "=== 4) 守护日志尾部 ==="
sudo tail -10 /var/log/thermal_guard.log
echo
echo "=== 5) 服务 ==="
for s in zynq-desktop zynq-audio zynq-agent; do printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"; done
echo
echo "=== 6) 器件温度等级（从 part number 判断）==="
echo "  部分型号: xc7z020clg400-2  （-2 是速度等级）"
echo "  商业级 Tj 上限 = 85°C / 工业级 = 100°C"
echo
echo "=== 7) 有没有热关机记录 ==="
sudo dmesg 2>/dev/null | grep -iE "thermal|over.?temp|shutdown" | tail -5 || echo "  (无)"