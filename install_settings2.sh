#!/bin/bash
set -e
cd /home/zynq/ui
echo "=== 重新生成提示音（幅度 0.35 -> 0.95）==="
python3 - <<'PY'
import sys, os
sys.path.insert(0, "/home/zynq/ui")
import chime
os.makedirs("/home/zynq/Music/提示音", exist_ok=True)
for k in chime.STYLES:
    p = "/home/zynq/Music/提示音/%s.wav" % k
    s = chime.make_chime(k)
    chime.write_wav(s, p)
    print("  %-8s 峰值=%-6d %.2fs" % (k, max(abs(x) for x in s), len(s)/44100.0))
PY
echo "=== 默认提示音也重新生成 ==="
python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
import chime
chime.write_wav(chime.make_chime('apple'), '/home/zynq/Music/提示音.wav')
print('  提示音.wav 已更新')
"
echo "=== 把服务音量设成 28 ==="
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"v":28}' \
  http://127.0.0.1:8767/volume; echo
echo "=== 重启桌面加载新设置 App ==="
sudo systemctl restart zynq-desktop
sleep 9
systemctl is-active zynq-desktop