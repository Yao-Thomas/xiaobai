#!/usr/bin/env bash
echo "=== 点开始菜单里的「时钟」（340, 456）==="
echo "340,456" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
sudo tail -3 /var/log/zynq-desktop.log | sed 's/^/  /'
echo
echo "=== 表盘1 数字 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/c1.raw 2>/dev/null && echo "  ok"
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/c1b.raw 2>/dev/null
if [ "$(md5sum /tmp/c1.raw|cut -d' ' -f1)" = "$(md5sum /tmp/c1b.raw|cut -d' ' -f1)" ]; then
  echo "  画面没变（可能没在动）"
else
  echo "  ✓ 画面在变 -> 动画在跑"
fi
echo
echo "=== 切到表盘2 指针（按钮 x≈150, y≈79）==="
echo "150,79" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/c2.raw 2>/dev/null && echo "  ok"
sleep 1.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/c2b.raw 2>/dev/null
[ "$(md5sum /tmp/c2.raw|cut -d' ' -f1)" = "$(md5sum /tmp/c2b.raw|cut -d' ' -f1)" ] \
  && echo "  画面没变" || echo "  ✓ 秒针在动"
echo
echo "=== 切到表盘3 世界 ==="
echo "250,79" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/c3.raw 2>/dev/null && echo "  ok"
echo
echo "=== 切到表盘4 秒表 ==="
echo "350,79" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/c4.raw 2>/dev/null && echo "  ok"
echo
echo "=== 日志 ==="
sudo tail -6 /var/log/zynq-desktop.log | sed 's/^/  /'
