#!/bin/bash
echo "=== 造测试图片 ==="
mkdir -p /home/zynq/Pictures
python3 - <<'EOF'
from PIL import Image
for i in range(3):
    im = Image.new("RGB", (400, 300), (30 + i * 60, 90, 210 - i * 50))
    im.save("/home/zynq/Pictures/test_%d.png" % i)
print("已生成 3 张测试图")
EOF
ls -la /home/zynq/Pictures/

echo ""
echo "=== 重启桌面 ==="
rm -rf /home/zynq/ui/__pycache__
systemctl restart zynq-desktop
sleep 12
echo -n "服务: "; systemctl is-active zynq-desktop
echo "--- 日志 ---"
tail -4 /var/log/zynq-desktop.log

echo ""
echo "=== 下载验证: 画板 up 事件 / 图片删除 ==="
cd /home/zynq/ui
python3 - <<'EOF'
import sys
sys.path.insert(0, "/home/zynq/ui")
# 静态检查: 关键代码在不在
src = open("apps_draw.py", encoding="utf-8").read()
print("  画板处理 'up' :", "✅" if '"up"' in src or "'up'" in src else "❌")
print("  画板处理 'down':", "✅" if '"down"' in src or "'down'" in src else "❌")
v = open("apps_view.py", encoding="utf-8").read()
print("  图片删除功能  :", "✅" if "confirm_del" in v and "os.remove" in v else "❌")
fb = open("fbui.py", encoding="utf-8").read()
print("  触摸上报抬笔  :", "✅" if '("up"' in fb else "❌")
EOF
echo DONE
