echo "=== 1) CPU 频率 / 调频策略 ==="
for c in /sys/devices/system/cpu/cpu0/cpufreq; do
  [ -d "$c" ] || { echo "  (没有 cpufreq)"; continue; }
  for f in scaling_governor scaling_cur_freq cpuinfo_cur_freq scaling_min_freq scaling_max_freq; do
    [ -f "$c/$f" ] && echo "  $f = $(cat $c/$f 2>/dev/null)"
  done
done
echo
echo "=== 2) CPU 占用前几名 ==="
ps -eo pcpu,pid,comm --sort=-pcpu | head -8
echo
echo "=== 3) PL 侧有没有东西在跑（自研 IP 的 ap_ctrl）==="
sudo python3 - <<'PYEOF'
import mmap, os, struct
for name, base in [("gpu_0",0x43CB0000), ("scope_0",0x43CC0000),
                   ("cnn_conv",0x43CD0000), ("cnn_fc",0x43CE0000),
                   ("audio_fmt",0x43C50000), ("i2s_rx",0x43C60000), ("i2s_tx",0x43C70000)]:
    pid = os.fork()
    if pid == 0:
        try:
            fd = os.open("/dev/mem", os.O_RDONLY|os.O_SYNC)
            m = mmap.mmap(fd, 256, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
            vals = " ".join("%02X" % m[o] for o in range(0, 16, 4))
            print("  %-10s @0x%08X  %s" % (name, base, vals))
            os._exit(0)
        except Exception:
            print("  %-10s @0x%08X  (读不了)" % (name, base)); os._exit(1)
    os.waitpid(pid, 0)
PYEOF
echo
echo "=== 4) 有没有风扇 / PWM ==="
ls /sys/class/hwmon/ 2>/dev/null
ls /sys/devices/platform/ 2>/dev/null | grep -iE "fan|pwm" | head -5
echo
echo "=== 5) 电压（XADC）==="
for v in vccint vccaux vccbram vccpint vccpaux vccddr; do
  f=/sys/bus/iio/devices/iio:device0/in_voltage*_${v}_raw
  for g in $f; do
    [ -f "$g" ] || continue
    echo "  $(basename $g) = $(cat $g)"
  done
done