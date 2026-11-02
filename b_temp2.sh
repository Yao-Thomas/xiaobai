echo "=== 1) 当前时间 / 运行时长 ==="
date
uptime
echo
echo "=== 2) 温度计算 ==="
R=$(cat /sys/bus/iio/devices/iio:device0/in_temp0_raw)
S=$(cat /sys/bus/iio/devices/iio:device0/in_temp0_scale)
O=$(cat /sys/bus/iio/devices/iio:device0/in_temp0_offset)
echo "  raw=$R scale=$S offset=$O"
python3 -c "
r,s,o = $R, $S, $O
mc = (r + o) * s
print('  ★ 温度 = %.1f °C' % (mc/1000.0))
print('  (裸 millidegree = %.0f)' % mc)
"
echo
echo "=== 3) 重启原因（内核日志开头）==="
sudo journalctl -b -1 -n 5 --no-pager 2>/dev/null | tail -5
echo "  --- 上次关机前 ---"
sudo journalctl --list-boots 2>/dev/null | tail -4
echo
echo "=== 4) 本次启动时间点 ==="
sudo journalctl -b --no-pager 2>/dev/null | head -3
echo
echo "=== 5) 温度趋势（采样 6 次，每 2 秒）==="
for i in 1 2 3 4 5 6; do
  R=$(cat /sys/bus/iio/devices/iio:device0/in_temp0_raw)
  python3 -c "print('    %s  %.1f °C   load=%s' % ('$i', ($R + ($O)) * ($S) / 1000.0, open('/proc/loadavg').read().split()[0]))"
  sleep 2
done