#!/bin/sh
# check_app.sh —— 检查应用能否导入 + 桌面进程状态
echo "=== 1. 桌面进程 ==="
ps -ef | grep '[d]esktop.py' | head -2

echo
echo "=== 2. 应用能否导入（抓报错）==="
cat > /tmp/_imp.py <<'PYEOF'
import sys, traceback
sys.path.insert(0, '/home/zynq/ui')
try:
    import apps_scope_dual as A
    print("  import OK; do_auto 存在 =", hasattr(A.App, "do_auto"))
except Exception:
    traceback.print_exc()
PYEOF
python3 /tmp/_imp.py 2>&1 | tail -14

echo
echo "=== 3. 真跑一次 run() 的前几秒（抓异常）==="
cat > /tmp/_run.py <<'PYEOF'
import sys, traceback, time
sys.path.insert(0, '/home/zynq/ui')
from fbui import Screen, Touch
import apps_scope_dual as A
try:
    scr = Screen()
    scr.flush = lambda box=None: None      # 不写显存
    touch = Touch()
    app = A.App(scr)
    app.make_bg()
    app.full_redraw()
    ok = False
    for i in range(600):
        app.step()
        if i < 400:
            if app.do_auto():
                print("  AUTO 在第 %d 轮成功: 时基=%s V/div=%s" %
                      (i, app.m.tb.label(),
                       __import__("scope_model").VDIV_NAMES[app.m.ch[0].vdiv_idx]))
                ok = True
                break
        time.sleep(0.004)
    if not ok:
        mm = app.m.m[app.m.active]
        print("  AUTO 未触发; locked=%s 频率=%s vpp=%s" %
              (mm.get("locked"), mm.get("freq"), mm.get("vpp")))
    print("  RUN_OK")
except Exception:
    traceback.print_exc()
PYEOF
python3 /tmp/_run.py 2>&1 | tail -16
echo "CHECK_APP_DONE"
