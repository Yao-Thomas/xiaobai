#!/bin/bash
# restore_and_play.sh —— 恢复放音 + 放一首歌试听（用户已同意）
set -u

echo "=============================================================="
echo " 恢复放音 $(date '+%T')"
echo "=============================================================="
echo
echo "--- 1) 放回单元文件 ---"
if [ ! -f /etc/systemd/system/zynq-audio.service ]; then
  sudo mv /root/zynq-audio.service.disabled \
          /etc/systemd/system/zynq-audio.service && echo "  已放回"
  sudo systemctl daemon-reload && echo "  daemon-reload 完成"
else
  echo "  已在原位"
fi
echo
echo "--- 2) 启动音频服务 ---"
sudo systemctl start zynq-audio
sleep 4
echo -n "  is-active: "; systemctl is-active zynq-audio
echo
echo "--- 3) 解除静音锁 ---"
sudo rm -f /etc/zynq-silent
echo -n "  /etc/zynq-silent: "; [ -f /etc/zynq-silent ] && echo 仍在 || echo 已解除
echo
echo "--- 4) 恢复 codec（关键：上轮静默实验把 DAC 留在 -96dB）---"
sudo bash /tmp/codec_reset.sh 2>&1 | tail -8
echo
echo "--- 5) 音量拉到最大 ---"
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' \
  -d '{"v":33}' http://127.0.0.1:8767/volume; echo
echo
echo "--- 6) 音乐目录 ---"
ls -l /home/zynq/Music/*.wav 2>/dev/null | awk '{print "  "$5" 字节  "$9}'
echo
echo "--- 7) 服务状态 ---"
curl -s --max-time 15 http://127.0.0.1:8767/state; echo
