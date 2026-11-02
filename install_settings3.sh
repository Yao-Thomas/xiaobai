#!/bin/bash
cd /home/zynq/ui
echo "=== 重新生成默认提示音（root 所有，需要 sudo）==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
import chime
chime.write_wav(chime.make_chime('apple'), '/home/zynq/Music/提示音.wav')
print('  提示音.wav 已更新, 峰值', max(abs(x) for x in chime.make_chime('apple')))
"
sudo chown zynq:zynq /home/zynq/Music/提示音.wav 2>/dev/null || true
sudo chmod 664 /home/zynq/Music/提示音.wav 2>/dev/null || true
ls -l /home/zynq/Music/提示音.wav
echo
echo "=== 提示音目录 ==="
ls -l /home/zynq/Music/提示音/ | head -12
echo
echo "=== 把输出音量设成 28 ==="
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"v":28}' \
  http://127.0.0.1:8767/volume; echo
echo
echo "=== 重启桌面加载新设置 App ==="
sudo systemctl restart zynq-desktop
sleep 9
systemctl is-active zynq-desktop
echo "=== 音频服务 ==="
systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
