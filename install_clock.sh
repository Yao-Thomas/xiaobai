#!/usr/bin/env bash
# 把「时钟」App 注册进桌面
set -e
cd /home/zynq/ui

echo "=== 1) 备份 desktop.py ==="
sudo cp desktop.py desktop.py.bak_clock_$(date +%Y%m%d_%H%M%S)
ls -l desktop.py.bak_clock_* | tail -1 | sed 's/^/  /'
echo

echo "=== 2) 检查 math 是否已导入 ==="
grep -n "^import math\|^import \|^from " desktop.py | head -12 | sed 's/^/  /'
echo

echo "=== 3) 插入 icon_clock 图标函数 + 注册 App ==="
sudo python3 - <<'PY'
import io, re
p = "/home/zynq/ui/desktop.py"
s = io.open(p, encoding="utf-8").read()

if "icon_clock" in s:
    print("  已经注册过，跳过")
    raise SystemExit(0)

# 确保有 math
if not re.search(r"^import math$", s, re.M):
    s = s.replace("import os", "import math\nimport os", 1)

ICON = '''

def icon_clock(d, x, y, s):
    """时钟: 圆形表盘 + 刻度 + 时分针"""
    cx, cy = x + s / 2.0, y + s / 2.0
    R = s * 0.37
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=W, width=3)
    for i in range(12):
        a = math.radians(i * 30 - 90)
        r1, r2 = R * (0.76 if i % 3 == 0 else 0.83), R * 0.92
        d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
               fill=W, width=3 if i % 3 == 0 else 2)
    for ang, ln, wd in ((-55, 0.42, 4), (35, 0.64, 3)):
        a = math.radians(ang - 90)
        d.line([cx, cy, cx + R * ln * math.cos(a), cy + R * ln * math.sin(a)],
               fill=W, width=wd)
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=W)


APPS = ['''

s = s.replace("\nAPPS = [", ICON, 1)

# 在「计算器」后面插入时钟
s = s.replace(
    '{"name": "计算器",   "mod": "apps_calc",  "icon": icon_calc,  "tint": (240, 160, 50)},',
    '{"name": "计算器",   "mod": "apps_calc",  "icon": icon_calc,  "tint": (240, 160, 50)},\n'
    '    {"name": "时钟",     "mod": "apps_clock", "icon": icon_clock, "tint": (255, 149, 0)},',
    1)

io.open(p, "w", encoding="utf-8").write(s)
print("  已插入 icon_clock 并注册「时钟」")
PY
echo

echo "=== 4) 校验 ==="
python3 -c "import ast; ast.parse(open('/home/zynq/ui/desktop.py').read()); print('  desktop.py 语法 OK')"
python3 -c "import ast; ast.parse(open('/home/zynq/ui/apps_clock.py').read()); print('  apps_clock.py 语法 OK')"
grep -n "apps_clock\|icon_clock" /home/zynq/ui/desktop.py | sed 's/^/  /'
echo

echo "=== 5) 试导入（能抓出运行时错误）==="
cd /home/zynq/ui && sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
import apps_clock
print('  apps_clock 导入 OK')
print('  表盘:', apps_clock.FACES)
print('  城市:', [c[0] for c in apps_clock.CITIES])
" 2>&1 | tail -8
echo

echo "=== 6) 重启桌面 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  zynq-desktop: "; systemctl is-active zynq-desktop
sudo tail -6 /var/log/zynq-desktop.log | sed 's/^/  /'
