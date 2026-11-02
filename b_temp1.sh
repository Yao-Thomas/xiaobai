echo "=== 1) thermal zone ==="
for z in /sys/class/thermal/thermal_zone*; do
  [ -d "$z" ] || continue
  echo "  $(basename $z): type=$(cat $z/type 2>/dev/null) temp=$(cat $z/temp 2>/dev/null)"
done
echo
echo "=== 2) hwmon ==="
for h in /sys/class/hwmon/hwmon*; do
  [ -d "$h" ] || continue
  echo "  $(basename $h): name=$(cat $h/name 2>/dev/null)"
  for f in $h/temp*_input $h/temp*_label; do
    [ -f "$f" ] && echo "     $(basename $f) = $(cat $f 2>/dev/null)"
  done
done
echo
echo "=== 3) iio (XADC) 设备 ==="
ls -d /sys/bus/iio/devices/* 2>/dev/null
for d in /sys/bus/iio/devices/iio:device*; do
  [ -d "$d" ] || continue
  echo "  --- $d  name=$(cat $d/name 2>/dev/null) ---"
  ls $d 2>/dev/null | grep -iE "temp|volt" | head -12
  for f in $d/in_temp*_raw $d/in_temp*_scale $d/in_temp*_offset; do
    [ -f "$f" ] && echo "     $(basename $f) = $(cat $f 2>/dev/null)"
  done
done
echo
echo "=== 4) 有没有 xadc 驱动 ==="
lsmod | grep -iE "xadc|iio" || echo "  (lsmod 里没有)"
ls /sys/bus/platform/drivers/ 2>/dev/null | grep -iE "xadc|iio"
echo
echo "=== 5) 当前负载（热源）==="
uptime
cat /proc/loadavg
echo
echo "=== 6) 有没有 thermal 相关的内核日志 ==="
sudo dmesg 2>/dev/null | grep -iE "thermal|xadc|temp" | head -8