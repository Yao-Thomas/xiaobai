#!/usr/bin/env bash
echo "=== 点开始菜单里的「时钟」(340,456) ==="
echo "340,456" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "  日志:"
sudo tail -3 /var/log/zynq-desktop.log | sed 's/^/    /'
echo
echo "=== 表盘1 数字：连续抓两次看动画 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k1.raw 2>/dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k1b.raw 2>/dev/null
if [ "$(md5sum /tmp/k1.raw|cut -d' ' -f1)" = "$(md5sum /tmp/k1b.raw|cut -d' ' -f1)" ]; then
  echo "  ✗ 画面没变"
else
  echo "  ✓ 动画在跑（秒在走）"
fi
sudo tail -2 /var/log/zynq-desktop.log | sed 's/^/    /'