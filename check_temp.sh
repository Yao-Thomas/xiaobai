#!/bin/bash
echo "=== 板上有哪些温度源 ==="
for p in /sys/class/thermal/thermal_zone0/temp \
         /sys/class/thermal/thermal_zone0/type \
         /sys/class/hwmon/hwmon0/temp1_input \
         /sys/devices/soc0/amba/f8007100.adc/iio:device0/in_temp0_raw \
         /sys/bus/iio/devices/iio:device0/in_temp0_raw ; do
  if [ -f "$p" ]; then
    echo "  [有] $p = $(cat $p 2>/dev/null)"
  else
    echo "  [无] $p"
  fi
done
echo
echo "=== 所有 iio 设备 ==="
ls /sys/bus/iio/devices/ 2>/dev/null
for d in /sys/bus/iio/devices/iio:device*; do
  [ -d "$d" ] || continue
  echo "  $d  name=$(cat $d/name 2>/dev/null)"
  ls $d | grep -i temp | head -4 | sed 's/^/      /'
done
echo
echo "=== XADC 的 hwmon ==="
for h in /sys/class/hwmon/hwmon*; do
  [ -d "$h" ] || continue
  echo "  $h name=$(cat $h/name 2>/dev/null)"
  ls $h | grep -i temp | head -4 | sed 's/^/      /'
done