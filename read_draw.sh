echo "=== 1) MENU_BTN 坐标 ==="
grep -n "MENU_BTN" /home/zynq/ui/home.py | sed 's/^/  /'
echo
echo "=== 2) draw() 里 1055-1080（是否画 taskbar）==="
sed -n '1055,1080p' /home/zynq/ui/desktop.py | cat -n | awk '{printf "  %4d: %s\n", $1+1054, substr($0, index($0,$2))}'
echo
echo "=== 3) 1250-1275 ==="
sed -n '1250,1275p' /home/zynq/ui/desktop.py | cat -n | awk '{printf "  %4d: %s\n", $1+1249, substr($0, index($0,$2))}'
echo
echo "=== 4) home.hit() 里 menu 判定（945-960）==="
sed -n '945,960p' /home/zynq/ui/home.py | cat -n | awk '{printf "  %4d: %s\n", $1+944, substr($0, index($0,$2))}'