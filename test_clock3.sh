#!/usr/bin/env bash
echo "=== 1) 确认新代码已上板（不该再出现 rounded_rectangle）==="
grep -n "rounded_rectangle" /home/zynq/ui/apps_clock.py | sed 's/^/  /'
echo "  （上面只应出现注释行，不该有 d.rounded_rectangle 调用）"
grep -c "scr.rrect" /home/zynq/ui/apps_clock.py | sed 's/^/  scr.rrect 用了 /'
echo
echo "=== 2) 重启桌面（清掉内存里的旧模块）==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  is-active: "; systemctl is-active zynq-desktop
echo
echo "=== 3) 进应用页 → 点时钟 ==="
echo "378,550" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "340,456" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "  日志:"
sudo tail -5 /var/log/zynq-desktop.log | sed 's/^/    /'
echo
echo "=== 4) 数字表盘：抓两次看动画 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k1.raw 2>/dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k1b.raw 2>/dev/null
if [ "$(md5sum /tmp/k1.raw|cut -d' ' -f1)" = "$(md5sum /tmp/k1b.raw|cut -d' ' -f1)" ]; then
  echo "  ✗ 没动"
else
  echo "  ✓ 动画在跑"
fi
echo
echo "=== 5) 有没有新的异常 ==="
sudo tail -20 /var/log/zynq-desktop.log | grep -a -A5 "Error\|Traceback" | tail -8 | sed 's/^/  /'
