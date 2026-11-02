#!/bin/sh
# thermal_watch.sh —— 紧急监测：温度还在涨还是平稳了
#
# 背景：停桌面、降背光都没用，温度从 70 一路爬到 85.8°C。
#       现在桌面和音频已经被守护停掉了，看这样能不能稳住。
#
# 判读：
#   平稳/下降  -> 守护的"停机"策略有效，可以留在停机状态等用户回来
#   继续上升   -> 软件手段无效，必须断电保护硬件

echo "======================================================"
echo " 紧急温度监测（每 10 秒一次，共 4 分钟）"
echo "======================================================"
echo " 桌面=$(systemctl is-active zynq-desktop) 音频=$(systemctl is-active zynq-audio)"
echo

TEMP() { /usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null; }
FIRST=""
LAST=""
i=0
while [ $i -lt 24 ]; do
  T=$(TEMP)
  [ -z "$FIRST" ] && FIRST="$T"
  LAST="$T"
  printf "  %s  %5s°C  load=%s  raw=%s\n" \
    "$(date +%H:%M:%S)" "$T" "$(cut -d' ' -f1 /proc/loadavg)" \
    "$(cat /sys/bus/iio/devices/iio:device0/in_temp0_raw)"
  i=$((i+1))
  sleep 10
done
echo
echo "起始=$FIRST  结束=$LAST"
/usr/bin/python3 -c "
f=$FIRST; l=$LAST
d=l-f
print('  变化: %+.1f°C' % d)
if d > 1.0:   print('  ★★★ 还在上升 —— 软件降温无效，建议断电')
elif d > -0.5: print('  ★ 基本平稳 —— 可以留在停机状态')
else:          print('  ✓ 在下降 —— 停机策略有效')
"
