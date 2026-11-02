#!/usr/bin/env bash
LOG=/var/log/zynq-desktop.log
echo "=== 底部页码点：3 个点约在 (815,550) (835,550) (855,550) ==="
for x in 835 855; do
  echo "  点 ($x,550)"
  echo "$x,550" | sudo tee /tmp/ui_tap > /dev/null
  sleep 2.5
  sudo python3 /home/zynq/ui/shot_fb.py /tmp/pg_$x.raw 2>/dev/null
done
echo
echo "=== 日志 ==="
sudo tail -5 $LOG | sed 's/^/  /'
echo
echo "=== 顺便：网格里到底有没有时钟（从 APPS 配置看是有的）==="
grep -n '"时钟"' /home/zynq/ui/desktop.py | sed 's/^/  /'
