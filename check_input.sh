#!/bin/bash
echo "=== 1) desktop.py 怎么读触摸/输入 ==="
grep -nE "evdev|/dev/input|touch|poll|read_event|ui_tap|FIFO|mkfifo" /home/zynq/ui/desktop.py | head -20
echo
echo "=== 2) 框架里 run() 的签名和输入来源 ==="
grep -nE "^def run|def run\(|class .*App|def main" /home/zynq/ui/desktop.py | head -10
echo
echo "=== 3) 输入设备 ==="
ls /dev/input/ 2>/dev/null
echo
echo "=== 4) desktop.py 里 apps_music 是怎么加载的 ==="
sed -n '400,440p' /home/zynq/ui/desktop.py