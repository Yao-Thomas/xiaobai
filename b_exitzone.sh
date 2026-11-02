echo "=== 1) EXIT_ZONE 定义 ==="
grep -nE "EXIT_ZONE" /home/zynq/ui/desktop.py | head -5
echo
echo "=== 2) _guard 实现 ==="
sed -n '/def _guard/,/^    def /p' /home/zynq/ui/fbui.py | head -20
echo
echo "=== 3) 本地模拟：注入 tap 到 poll(move=True) 看返回什么 ==="
cd /home/zynq/ui
python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, '/home/zynq/ui')
# 不真正打开设备，直接测 _load_inject 的逻辑
open('/tmp/ui_tap','w').write("500,33")
import fbui
t = fbui.Touch.__new__(fbui.Touch)
t._inj = []
t._pend = []
t.exit_zone = None
t.down = False
t.sx = t.sy = t.x = t.y = 0
t.x = 0; t.y = 0
r = t._load_inject()
print("  _load_inject('500,33') ->", r)
PYEOF
echo
echo "=== 4) 桌面对应用的触摸是怎么走的（找 touch.poll 调用链）==="
grep -nE "exit_zone|ExitApp|resume|def _run_|mod.run" /home/zynq/ui/desktop.py | head -12