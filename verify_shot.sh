#!/usr/bin/env bash
# 验证截图可靠性：间隔 5 秒抓 3 次，只看时钟区域
echo "=== 直接读 fb0，间隔 5 秒，共 3 次 ==="
for i in 1 2 3; do
  # 只读右上角时钟那一条（y=0..30，x=760..1024），省时间
  # 行内偏移 = 760*3 = 2280，行跨 3072
  sudo dd if=/dev/fb0 of=/tmp/clk_$i.raw bs=1 skip=$((0*3072 + 2280)) count=$((30*3072)) 2>/dev/null
  echo "  第 $i 次: md5=$(md5sum /tmp/clk_$i.raw | cut -d' ' -f1)  时间=$(date +%H:%M:%S)"
  [ $i -lt 3 ] && sleep 5
done
echo
echo "=== 三次是否相同 ==="
a=$(md5sum /tmp/clk_1.raw | cut -d' ' -f1)
b=$(md5sum /tmp/clk_2.raw | cut -d' ' -f1)
c=$(md5sum /tmp/clk_3.raw | cut -d' ' -f1)
[ "$a" = "$b" ] && [ "$b" = "$c" ] && echo "  ✗ 三次都相同" || echo "  ✓ 有变化 -> 截图工具可靠，桌面在刷新"
echo
echo "=== 再看整屏（间隔 5 秒两次）==="
sudo dd if=/dev/fb0 of=/tmp/f1.raw bs=3072 count=600 2>/dev/null
md5sum /tmp/f1.raw
sleep 5
sudo dd if=/dev/fb0 of=/tmp/f2.raw bs=3072 count=600 2>/dev/null
md5sum /tmp/f2.raw
[ "$(md5sum /tmp/f1.raw | cut -d' ' -f1)" = "$(md5sum /tmp/f2.raw | cut -d' ' -f1)" ] \
  && echo "  ✗ 整屏相同" || echo "  ✓ 整屏有变化"
