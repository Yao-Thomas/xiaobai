#!/bin/bash
sudo systemctl restart zynq-agent; sleep 5
systemctl is-active zynq-agent
echo
echo "===== 测试静音锁：调 speak 工具（应该被拒）====="
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"name":"speak","args":{"text":"我应该说不出这句话"}}' \
  http://127.0.0.1:8765/tool | head -c 500; echo
echo
echo "===== 测试静音锁：调 audio 工具（应该被拒）====="
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"name":"audio","args":{"action":"selftest"}}' \
  http://127.0.0.1:8765/tool | head -c 500; echo
echo
echo "===== 确认音频服务仍是停的 ====="
echo -n "zynq-audio: "; systemctl is-active zynq-audio
echo -n "enabled:    "; systemctl is-enabled zynq-audio 2>&1
echo -n "静音锁文件: "; ls -l /etc/zynq-silent 2>/dev/null | awk '{print "存在"}'