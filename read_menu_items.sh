echo "=== 1) menu_items()：开始菜单格子怎么算的 ==="
sed -n '955,1000p' /home/zynq/ui/desktop.py | cat -n | awk '{printf "  %4d: %s\n", $1+954, substr($0, index($0,$2))}'
echo
echo "=== 2) draw_menu() 里格子尺寸 ==="
grep -n "def draw_menu" -A 25 /home/zynq/ui/desktop.py | sed 's/^/  /'