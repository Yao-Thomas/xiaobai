#!/bin/bash
set -e
# 1) 生成全部提示音（不出声）
cd /home/zynq/ui
python3 - <<'PY'
import sys, os
sys.path.insert(0, "/home/zynq/ui")
import chime
os.makedirs("/home/zynq/Music/提示音", exist_ok=True)
for k in chime.STYLES:
    p = "/home/zynq/Music/提示音/%s.wav" % k
    s = chime.make_chime(k)
    chime.write_wav(s, p)
    print("  %-8s %-8s %.2fs" % (k, chime.STYLE_NAMES[k], len(s)/44100.0))
PY
# 2) 图标布局
sudo python3 /tmp/add_chime_icon.py
sudo cp /tmp/_pages.json /home/zynq/.desktop_pages
sudo chmod 644 /home/zynq/.desktop_pages
# 3) 重启桌面
sudo systemctl restart zynq-desktop
sleep 9
echo "--- 图标第1页 ---"
cat /home/zynq/.desktop_pages; echo
systemctl is-active zynq-desktop