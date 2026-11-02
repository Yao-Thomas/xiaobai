echo "=== A) 画「开始」按钮的地方（1120-1160）==="
sed -n '1120,1160p' /home/zynq/ui/desktop.py | cat -n | awk '{printf "  %4d: %s\n", $1+1119, substr($0, index($0,$2))}'
echo
echo "=== B) 点击处理：开始菜单段（1490-1530）==="
sed -n '1490,1530p' /home/zynq/ui/desktop.py | cat -n | awk '{printf "  %4d: %s\n", $1+1489, substr($0, index($0,$2))}'
echo
echo "=== C) 「旧任务栏的开始按钮」（1555-1580）==="
sed -n '1555,1580p' /home/zynq/ui/desktop.py | cat -n | awk '{printf "  %4d: %s\n", $1+1554, substr($0, index($0,$2))}'
echo
echo "=== D) TB_H / TB_ 定义 ==="
grep -n "TB_H\|TB_W\|TB_X\|TB_Y" /home/zynq/ui/desktop.py | head -12 | sed 's/^/  /'