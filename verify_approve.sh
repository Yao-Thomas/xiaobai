#!/bin/bash
# 验证点了「同意」之后动作真的执行了
echo "--- /tmp/demo_approval 存在吗 ---"
ls -l /tmp/demo_approval 2>&1 | head -1
echo
echo "--- 权限层状态 ---"
curl -s --max-time 10 http://127.0.0.1:8765/pending | python3 -c "
import json,sys
d=json.load(sys.stdin)
p=d['policy']
print('  待批准     :', p['pending'])
print('  5分钟内已批准:', p['approved_active'])
print('  静音锁     :', p['silent'])
"
echo
echo "--- 重试同一条命令（应该直接执行，不再要批准）---"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/demo_approval2"}}' \
  http://127.0.0.1:8765/tool | head -c 250
echo
ls -l /tmp/demo_approval2 2>&1 | head -1
echo
echo "--- 音频服务仍封锁 ---"
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
