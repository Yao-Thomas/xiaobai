#!/bin/bash
# 启动板载音频服务并做基本自检
sudo pkill -f audio_svc.py 2>/dev/null
sleep 1
cd /home/zynq/ui || exit 1
sudo setsid nohup python3 -u audio_svc.py > /tmp/audio_svc.log 2>&1 < /dev/null &
sleep 9
echo "--- pid ---"
pgrep -af audio_svc.py
echo "--- log ---"
tail -25 /tmp/audio_svc.log
echo "--- health ---"
curl -s --max-time 8 http://127.0.0.1:8767/health; echo
echo "--- state ---"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
