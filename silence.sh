#!/bin/bash
echo "=== 杀掉所有测试脚本 ==="
sudo pkill -f matrix_vol.py 2>/dev/null && echo "  已杀 matrix_vol.py" || echo "  matrix_vol.py 没在跑"
sudo pkill -f bg_mvol.sh   2>/dev/null && echo "  已杀 bg_mvol.sh"   || echo "  bg_mvol.sh 没在跑"
sudo pkill -f voice_selftest 2>/dev/null || true
sudo pkill -f loopback_proof 2>/dev/null || true
sudo pkill -f config_compare 2>/dev/null || true
sleep 1
echo
echo "=== 确认没有残留 ==="
pgrep -af "matrix|bg_mvol|voice_selftest|loopback|config_compare|rec_|mic_" | grep -v pgrep || echo "  干净"
echo
echo "=== 把音频服务拉回来并静音 ==="
sudo systemctl start zynq-audio
sleep 6
systemctl is-active zynq-audio
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8767/stop; echo
echo "=== 状态（play_count 不再增长即为静音）==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
sleep 3
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
