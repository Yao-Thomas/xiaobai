echo "=== 1) draw_taskbar 被谁调用 ==="
grep -n "draw_taskbar" /home/zynq/ui/desktop.py | sed 's/^/  /'
echo
echo "=== 2) draw() 主函数（看画了哪些层）==="
grep -n "    def draw" -A 30 /home/zynq/ui/desktop.py | head -40 | sed 's/^/  /'
echo
echo "=== 3) home.py 的「全部应用」按钮几何 ==="
sed -n '494,512p' /home/zynq/ui/home.py | cat -n | awk '{printf "  %4d: %s\n", $1+493, substr($0, index($0,$2))}'
echo
echo "=== 4) home.py 里这个按钮的 hit 判定 ==="
grep -n "menu\|MENU_RECT\|全部应用" /home/zynq/ui/home.py | head -14 | sed 's/^/  /'