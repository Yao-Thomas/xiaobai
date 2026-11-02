#!/usr/bin/env bash
echo "=== 1) /var/log/zynq-desktop.log 大小与尾部 ==="
sudo ls -l /var/log/zynq-desktop.log 2>/dev/null
echo "  --- 尾部 30 行 ---"
sudo tail -30 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
echo
echo "=== 2) 有没有 Traceback ==="
sudo grep -n -A6 "Traceback" /var/log/zynq-desktop.log 2>/dev/null | tail -30 | sed 's/^/  /'
echo
echo "=== 3) 有没有 music 相关 ==="
sudo grep -n -i "music" /var/log/zynq-desktop.log 2>/dev/null | tail -10 | sed 's/^/  /'
echo
echo "=== 4) touch.poll 的实现（看会不会阻塞）==="
grep -n "class Touch" -A 45 /home/zynq/ui/*.py 2>/dev/null | grep -E "def poll|select|read|O_NONBLOCK|timeout|return" | head -12 | sed 's/^/  /'
echo
echo "=== 5) 主循环（看 poll 有没有超时）==="
grep -n "touch.poll\|def run" /home/zynq/ui/desktop.py | head -10 | sed 's/^/  /'
sed -n '1330,1360p' /home/zynq/ui/desktop.py | sed 's/^/  /'
