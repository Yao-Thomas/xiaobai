echo "=== 1) i2c 适配器列表 ==="
ls /dev/i2c-*
for f in /sys/class/i2c-dev/*/name; do
  [ -f "$f" ] && echo "  $(basename $(dirname $f)): $(cat $f)"
done
echo
echo "=== 2) ES8388 挂在哪个总线（看 sysfs）==="
ls -d /sys/bus/i2c/devices/* 2>/dev/null | while read d; do
  n=$(cat $d/name 2>/dev/null)
  case "$n" in
    *[Ee][Ss]8388*|*es8388*) echo "  ✓ $d  name=$n";;
  esac
done
echo
echo "=== 3) 带超时读寄存器 0x0A ==="
for bus in 1 0 2; do
  printf "  i2c-%s 0x0A: " $bus
  timeout 3 i2cget -y $bus 0x10 0x0A 2>&1 | head -1
done