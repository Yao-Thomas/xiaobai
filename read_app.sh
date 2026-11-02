echo "=== apps_music.py 结构 ==="
grep -n "^def \|^class \|^[A-Z_]* =\|def run\|draw\|title\|button\|列表\|btn" /home/zynq/ui/apps_music.py | head -40
echo
echo "=== 行数 ==="
wc -l /home/zynq/ui/apps_music.py