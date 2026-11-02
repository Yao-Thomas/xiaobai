echo "=== 系统 ==="
hostname
uptime
date
echo
echo "=== 服务 ==="
for s in zynq-desktop zynq-audio zynq-agent; do
  printf "  %-16s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo
echo "=== 音频设备 ==="
ls /dev/snd/ 2>/dev/null | tr '\n' ' '
echo
echo
echo "=== 关键设备节点 ==="
for d in /dev/fb0 /dev/i2c-1 /dev/input/event1 /dev/mem; do
  [ -e "$d" ] && echo "  ✓ $d" || echo "  ✗ $d"
done
echo
echo "=== 当前 bitstream 的 md5（对比刷新前后）==="
md5sum /mnt/boot/system.bit 2>/dev/null
ls -la /mnt/boot/system.bit 2>/dev/null