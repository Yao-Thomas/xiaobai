echo "=== 1) fbui.Screen 提供哪些绘图方法 ==="
grep -n "    def \|^def " /home/zynq/ui/fbui.py | head -45 | sed 's/^/  /'
echo
echo "=== 2) 一个简单 App 的完整结构（apps_calc.py）==="
sed -n '1,60p' /home/zynq/ui/apps_calc.py | sed 's/^/  /'
echo
echo "=== 3) desktop.py 里图标函数怎么写的（拿 icon_calc 当样板）==="
grep -n "def icon_calc" -A 18 /home/zynq/ui/desktop.py | sed 's/^/  /'
echo
echo "=== 4) APPS 注册格式 + COLS ==="
grep -n "APPS = \[" -A 24 /home/zynq/ui/desktop.py | sed 's/^/  /'