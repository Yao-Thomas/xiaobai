echo "=== 1) gpu.py 里的背光相关代码 ==="
grep -nE "backlight|背光|pwm|PWM|亮度" /home/zynq/ui/gpu.py | head -15
echo
echo "=== 2) pwmchip0 结构 ==="
ls -la /sys/class/pwm/pwmchip0/
echo "  npwm = $(cat /sys/class/pwm/pwmchip0/npwm 2>/dev/null)"
echo
echo "=== 3) 有没有已导出的 pwm ==="
ls -d /sys/class/pwm/pwmchip0/pwm* 2>/dev/null || echo "  (还没导出)"
echo
echo "=== 4) 设备树里的 pwm 节点 ==="
find /proc/device-tree -iname "*pwm*" 2>/dev/null | head -8
echo
echo "=== 5) 相关内核日志 ==="
sudo dmesg 2>/dev/null | grep -iE "pwm|backlight" | head -8
echo
echo "=== 6) LCD 相关 IP（从地址图里找）==="
grep -rnE "0x41200000|lcd" /home/zynq/ui/*.py 2>/dev/null | grep -iE "0x41" | head -6