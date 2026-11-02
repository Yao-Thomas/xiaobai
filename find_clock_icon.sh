#!/usr/bin/env bash
# 打开时钟 App，逐个表盘截图
echo "=== 1) 回桌面，进应用页找「时钟」 ==="
echo "60,30" | sudo tee /tmp/ui_tap > /dev/null       # 返回
sleep 1.5
echo "378,550" | sudo tee /tmp/ui_tap > /dev/null     # 应用
sleep 2.5
echo
echo "=== 2) 桌面日志（看有没有报错）==="
sudo tail -4 /var/log/zynq-desktop.log | sed 's/^/  /'
echo
echo "=== 3) 用 grep 找出图标在 APPS 里的序号 ==="
python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
import importlib.util
spec = importlib.util.spec_from_file_location("d", "/home/zynq/ui/desktop.py")
try:
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for i, a in enumerate(m.APPS):
        if a["name"] == "时钟":
            print("  时钟 在 APPS 索引 %d  (行 %d, 列 %d, 第 %d 页)"
                  % (i, i // m.COLS, i % m.COLS, i // (m.COLS * 2) + 1))
    print("  总应用数:", len(m.APPS), " COLS:", m.COLS)
except Exception as e:
    print("  读取失败:", e)
PY
