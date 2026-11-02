#!/usr/bin/env bash
LOG=/var/log/zynq-desktop.log
echo "=== 点「时钟」文字 (390,456) ==="
echo "390,456" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "  新日志（刚清空过，所以都是新的）:"
sudo tail -6 $LOG | sed 's/^/    /'
echo
echo "=== 抓两次看动画 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/t1.raw 2>/dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/t2.raw 2>/dev/null
if [ "$(md5sum /tmp/t1.raw|cut -d' ' -f1)" = "$(md5sum /tmp/t2.raw|cut -d' ' -f1)" ]; then
  echo "  ✗ 画面没变"
else
  echo "  ✓ 动画在跑！"
fi
echo
echo "=== 有没有新异常 ==="
sudo tail -30 $LOG | grep -a -A6 "Error\|Traceback" | tail -10 | sed 's/^/  /'
[ -z "$(sudo tail -30 $LOG | grep -a 'Error\|Traceback')" ] && echo "  （无异常）"
echo
echo "=== 逐个表盘（按钮 y≈79）==="
for spec in "150:指针" "250:世界" "350:秒表"; do
  x=${spec%%:*}; nm=${spec##*:}
  echo "150,79" | sudo tee /tmp/ui_tap > /dev/null 2>&1
  echo "  -> 点 ($x,79) 切到 $nm"
  echo "$x,79" | sudo tee /tmp/ui_tap > /dev/null
  sleep 2
  sudo python3 /home/zynq/ui/shot_fb.py /tmp/face_$x.raw 2>/dev/null
  sudo python3 - "$x" "$nm" <<'PY'
import sys
print("     已抓 表盘_%s (%s)" % (sys.argv[1], sys.argv[2]))
PY
done
sudo tail -4 $LOG | sed 's/^/    /'
