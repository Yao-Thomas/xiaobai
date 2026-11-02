echo "=== 1) 设备树里 ES8388 / 音频输入 的配置 ==="
for d in /proc/device-tree /sys/firmware/devicetree/base; do
  [ -d "$d" ] || continue
  echo "  --- $d ---"
  find $d -iname "*es8388*" -o -iname "*sound*" -o -iname "*i2s*" 2>/dev/null | head -8
  break
done
echo
echo "=== 2) codec 的 DAPM / 路由（看输入源）==="
sudo cat /sys/kernel/debug/asoc/*/dapm/* 2>/dev/null | head -5
ls /proc/asound/card0/ 2>/dev/null
echo
echo "=== 3) 声卡的 mixer 里有没有 Capture Source 枚举 ==="
sudo amixer -c 0 contents 2>/dev/null | grep -B1 -A6 -iE "input|source|mux" | head -30
echo
echo "=== 4) 板上有没有麦克风（看内核日志）==="
sudo dmesg 2>/dev/null | grep -iE "es8388|mic|asoc|i2s" | head -15