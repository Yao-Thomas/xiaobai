#!/usr/bin/env bash
echo "=== 1) Traceback 内容（用 -a 当文本读）==="
sudo grep -a -n -B2 -A12 "Traceback" /var/log/zynq-desktop.log 2>/dev/null | tail -40 | sed 's/^/  /'
echo
echo "=== 2) 主循环是否每轮都重绘（关键）==="
sed -n '1338,1345p' /home/zynq/ui/desktop.py | sed 's/^/  /'
echo "  --- 循环结尾（找 draw/flush）---"
awk 'NR>=1338 && NR<=1450 && (/draw\(\)/ || /flush\(\)/ || /sleep/ || /while True/)' /home/zynq/ui/desktop.py | head -12 | sed 's/^/  /'
echo
echo "=== 3) 循环总行数范围 ==="
awk 'NR>=1338 && /^    def /{print NR": "$0; exit}' /home/zynq/ui/desktop.py | sed 's/^/  /'
echo
echo "=== 4) fbui.Touch.poll 的完整实现 ==="
sed -n '420,470p' /home/zynq/ui/fbui.py | sed 's/^/  /'
