#!/usr/bin/env bash
set -e
echo "=== 1) 备份原服务 ==="
sudo cp /home/zynq/ui/audio_alsa_svc.py /home/zynq/ui/audio_alsa_svc.py.bak_formatfix_$(date +%Y%m%d_%H%M%S)
ls -l /home/zynq/ui/audio_alsa_svc.py.bak_* | tail -2
echo
echo "=== 2) 安装新版 ==="
sudo cp /home/zynq/ui/audio_alsa_svc_new.py /home/zynq/ui/audio_alsa_svc.py
sudo chown zynq:zynq /home/zynq/ui/audio_alsa_svc.py
python3 -c "import ast,sys; ast.parse(open('/home/zynq/ui/audio_alsa_svc.py').read()); print('  语法 OK')"
echo
echo "=== 3) 重启服务 ==="
sudo systemctl restart zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 4) 关键测试：播放【16kHz 单声道】这个之前必失败的文件 ==="
curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/录音_0928_144954.wav"}' \
  http://127.0.0.1:8767/play; echo
echo
echo "=== 5) 紧接着再播一个正常文件（验证没被占住）==="
curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/提示音.wav"}' \
  http://127.0.0.1:8767/play; echo
echo
echo "=== 6) 状态 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
