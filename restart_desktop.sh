#!/usr/bin/env bash
echo "=== 1) 重启桌面服务 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  zynq-desktop: "; systemctl is-active zynq-desktop
echo
echo "=== 2) 启动后有没有报错 ==="
sudo journalctl -u zynq-desktop -n 40 --no-pager 2>/dev/null | tail -12
echo
echo "=== 3) 音频服务确认在跑 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 4) 有没有输入注入工具（方便我自己点界面测试）==="
for t in evemu-event evemu-play xdotool; do
  command -v $t >/dev/null && echo "  有 $t" || echo "  无 $t"
done
echo
echo "=== 5) 触摸设备是哪个 ==="
for e in /dev/input/event*; do
  n=$(cat /sys/class/input/$(basename $e)/device/name 2>/dev/null)
  echo "  $e -> $n"
done
