#!/bin/bash
# 造一个待批准动作，然后看界面
B=http://127.0.0.1:8765
J='Content-Type: application/json'

echo "=== 1) 让 Agent 尝试一条会改系统的命令 ==="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/demo_approval"}}' $B/tool | head -c 300
echo
echo
echo "=== 2) 待批准队列 ==="
curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin)
p=d.get('policy',{})
print('  静音锁:', p.get('silent'), ' 待批准:', p.get('pending'))
for it in d.get('pending',[]):
    print('  id=%s' % it['id'])
    print('    动作:', it['payload'])
    print('    原因:', it['reason'])
"
