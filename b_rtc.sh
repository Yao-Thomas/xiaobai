echo "=== 1) RTC 设备 ==="
ls -la /dev/rtc* 2>/dev/null
ls /sys/class/rtc/ 2>/dev/null
for r in /sys/class/rtc/rtc*; do
  [ -d "$r" ] || continue
  echo "  --- $(basename $r) ---"
  for f in name date time since_epoch hctosys wakealarm max_user_freq; do
    [ -f "$r/$f" ] && echo "     $f = $(cat $r/$f 2>/dev/null)"
  done
done
echo
echo "=== 2) ★ RTC 唤醒支持 ==="
cat /sys/class/rtc/rtc0/wakealarm 2>/dev/null && echo "  (wakealarm 可读)"
echo "  /proc/driver/rtc:"
cat /proc/driver/rtc 2>/dev/null | head -15
echo
echo "=== 3) 电源管理支持 ==="
cat /sys/power/state 2>/dev/null
echo
echo "=== 4) ★ poweroff 后板子是真断电还是只停 CPU ==="
echo "  （看有没有 PMIC/regulator 控制）"
ls /sys/class/regulator/ 2>/dev/null | head -8
echo
echo "=== 5) 硬件看门狗（可作为复位源）==="
ls -la /dev/watchdog* 2>/dev/null || echo "  (没有 /dev/watchdog)"
ls /sys/class/watchdog/ 2>/dev/null
echo
echo "=== 6) 当前 RTC 时间 vs 系统时间 ==="
date
sudo hwclock -r 2>&1 | head -2