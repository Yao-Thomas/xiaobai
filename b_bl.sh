echo "=== 1) LCD 背光怎么控制的 ==="
grep -rln "backlight\|背光\|lcd_pl_pwm\|PWM" /home/zynq/ui/*.py /home/zynq/*.py 2>/dev/null | head -8
echo
echo "=== 2) 找背光/PWM 控制代码 ==="
grep -rnE "backlight|背光|亮度|pwm|PWM" /home/zynq/ui/desktop.py 2>/dev/null | head -12
echo
echo "=== 3) sysfs 背光 ==="
ls /sys/class/backlight/ 2>/dev/null || echo "  (没有 /sys/class/backlight)"
echo
echo "=== 4) PWM 相关 sysfs ==="
ls /sys/class/pwm/ 2>/dev/null || echo "  (没有 /sys/class/pwm)"
echo
echo "=== 5) 找 LCD/PWM 的 IP 地址 ==="
grep -rnE "0x41[0-9A-Fa-f]|lcd_id|PWM_AXI" /home/zynq/ui/*.py 2>/dev/null | head -8
echo
echo "=== 6) 亮度设置在哪 ==="
grep -rnE "bright|亮度|set_bright" /home/zynq/ui/*.py 2>/dev/null | head -10