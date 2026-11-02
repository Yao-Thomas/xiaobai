#!/bin/bash
# 用**完全相同**的命令重试 —— 这才是批准的验证方式
B=http://127.0.0.1:8765
J='Content-Type: application/json'

echo "=== 重发原命令: touch /tmp/demo_approval ==="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/demo_approval"}}' $B/tool | head -c 250
echo
echo "--- 文件建出来了吗 ---"
ls -l /tmp/demo_approval 2>&1 | head -1
echo
echo "=== 权限层状态 ==="
curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin); p=d['policy']
print('  待批准:', p['pending'], ' 已批准(5分钟内):', p['approved_active'])
for it in d.get('pending', []):
    print('  队列里:', it['payload'])
"
