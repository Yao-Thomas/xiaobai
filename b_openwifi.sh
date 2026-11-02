echo "=== 1) 网络卡片的点击逻辑 (desktop.py 565-590) ==="
sed -n '565,590p' /home/zynq/ui/desktop.py
echo
echo "=== 2) 应用网格布局常量 ==="
grep -nE "^COLS|^ROWS|^ICON_W|^ICON_H|^TB_H|MENU_COLS|def app_cells|def _cells" /home/zynq/ui/desktop.py | head -15
echo
echo "=== 3) WiFi 在 APPS 里的索引 ==="
python3 - <<'PYEOF'
import re
src = open('/home/zynq/ui/desktop.py', encoding='utf-8').read()
m = re.search(r'APPS\s*=\s*\[(.*?)\n\]', src, re.S)
if m:
    items = re.findall(r'"name":\s*"([^"]+)"', m.group(1))
    for i, n in enumerate(items):
        mark = "  <<< WiFi" if n == "WiFi" else ""
        print("  %2d  %s%s" % (i, n, mark))
PYEOF