#!/bin/bash
# 把音频服务装成开机自启的 systemd 服务
set -e
sudo pkill -f audio_svc.py 2>/dev/null || true
sleep 1
sudo install -m 0644 /home/zynq/ui/zynq-audio.service /etc/systemd/system/zynq-audio.service
sudo systemctl daemon-reload
sudo systemctl enable zynq-audio
sudo systemctl restart zynq-audio
sleep 8
echo "--- 服务状态 ---"
systemctl is-active zynq-audio
systemctl is-enabled zynq-audio
echo "--- health ---"
curl -s --max-time 10 http://127.0.0.1:8767/health; echo
echo "--- state ---"
curl -s --max-time 10 http://127.0.0.1:8767/state; echo
echo "--- 日志尾部 ---"
sudo journalctl -u zynq-audio --no-pager -n 12 2>&1 | tail -12
