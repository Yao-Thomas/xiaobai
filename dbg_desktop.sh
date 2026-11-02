#!/bin/bash
echo "=== [1] 停服务 + 清掉所有残留进程 ==="
systemctl stop zynq-desktop 2>/dev/null
pkill -9 -f "[d]esktop.py" 2>/dev/null
sleep 2
echo -n "残留 desktop 进程: "; pgrep -c -f "[d]esktop.py" || echo 0

echo ""
echo "=== [2] 前台运行 (最多 12 秒, 抓报错) ==="
cd /home/zynq/ui
timeout 12 python3 -u desktop.py 2>&1 | head -40
echo "退出码: $?"

echo ""
echo "=== [3] 单独测各步骤 ==="
python3 - <<'EOF'
import sys, traceback
sys.path.insert(0, "/home/zynq/ui")
print("--- import fbui ---")
try:
    import fbui
    print("  ok")
except Exception:
    traceback.print_exc(); raise SystemExit

print("--- Screen() ---")
try:
    s = fbui.Screen()
    print("  ok, phys=0x%08X" % (s.phys or 0))
except Exception:
    traceback.print_exc()

print("--- Touch() ---")
try:
    t = fbui.Touch()
    print("  ok")
except Exception:
    traceback.print_exc()

print("--- import desktop ---")
try:
    import desktop
    print("  ok, APPS=%d" % len(desktop.APPS))
except Exception:
    traceback.print_exc()

print("--- load_order ---")
try:
    d = desktop.Desktop.__new__(desktop.Desktop)
    d.apps = d.load_order()
    print("  ok, %d 个" % len(d.apps))
except Exception:
    traceback.print_exc()

print("--- make_wallpaper ---")
try:
    d.scr = fbui.Screen()
    w = d.make_wallpaper()
    print("  ok, %s" % (w.size,))
except Exception:
    traceback.print_exc()

print("--- try_gpu ---")
try:
    d.try_gpu()
    print("  ok")
except Exception:
    traceback.print_exc()
EOF
echo ""
echo "=== [4] 错误日志(journal) ==="
journalctl -u zynq-desktop --no-pager -n 15 2>/dev/null | tail -15
