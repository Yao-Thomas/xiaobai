#!/bin/bash
set -e
cd /home/zynq/ui
# 确保提示音文件都在
python3 - <<'PY'
import sys, os
sys.path.insert(0, "/home/zynq/ui")
import chime
os.makedirs("/home/zynq/Music/提示音", exist_ok=True)
n = 0
for k in chime.STYLES:
    p = "/home/zynq/Music/提示音/%s.wav" % k
    if not os.path.exists(p):
        chime.write_wav(chime.make_chime(k), p)
        n += 1
print("  提示音文件:", len(chime.STYLES), "个 (新生成 %d)" % n)
PY
# 图标布局
sudo python3 /tmp/add_settings_icon.py
sudo cp /tmp/_pages.json /home/zynq/.desktop_pages
sudo chmod 644 /home/zynq/.desktop_pages
# 重启桌面
sudo systemctl restart zynq-desktop
sleep 10
echo "--- 桌面服务 ---"
systemctl is-active zynq-desktop
echo "--- 图标第1页 ---"
cat /home/zynq/.desktop_pages; echo
echo "--- 设置 App 能不能 import ---"
python3 -c "import sys; sys.path.insert(0,'/home/zynq/ui'); import apps_settings; print('apps_settings OK, 页面:', sorted({a for a in ['main']}))" 2>&1 | tail -3
