#!/bin/bash
# 在板子上跑扫雷并收集诊断信息
echo "=== [1] 停掉旧进程 ==="
sudo pkill -9 -f mines.py 2>/dev/null
sleep 2
pgrep -af mines.py || echo "(没有残留)"

echo ""
echo "=== [2] framebuffer 真实参数 ==="
echo -n "virtual_size = "; cat /sys/class/graphics/fb0/virtual_size
echo -n "stride       = "; cat /sys/class/graphics/fb0/stride
echo -n "bpp          = "; cat /sys/class/graphics/fb0/bits_per_pixel
echo -n "name         = "; cat /sys/class/graphics/fb0/name 2>/dev/null

echo ""
echo "=== [3] 触摸设备 ==="
grep -B2 -A6 -i "goodix" /proc/bus/input/devices | grep -E "Name|Handlers"

echo ""
echo "=== [4] 关掉控制台光标闪烁 + 启动扫雷 ==="
sudo sh -c 'echo 0 > /sys/class/graphics/fbcon/cursor_blink' 2>/dev/null
sudo rm -f /tmp/mines.log
sudo setsid python3 /home/zynq/mines.py > /tmp/mines.log 2>&1 < /dev/null &
sleep 6

echo "--- 程序输出 ---"
sudo cat /tmp/mines.log 2>/dev/null
echo "--- 进程 ---"
pgrep -af mines.py || echo "(没起来!)"
echo ""
echo "DONE"
