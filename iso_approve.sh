#!/bin/bash
# 隔离测试：走 API（不走 UI），验证批准匹配
B=http://127.0.0.1:8765
J='Content-Type: application/json'
echo "=== 1) 清空队列 ==="
curl -s --max-time 10 -X POST -H "$J" -d '{}' $B/pending/clear; echo
echo "=== 2) 造一条新待批准 ==="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/iso_test"}}' $B/tool | head -c 200; echo
echo "=== 3) 拿 id ==="
ID=$(curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin)
ps=d.get('pending') or []
print(ps[0]['id'] if ps else '')
")
echo "  id=$ID"
echo "=== 4) 批准它 ==="
curl -s --max-time 10 -X POST -H "$J" -d "{\"id\":\"$ID\",\"ok\":true}" $B/approve; echo
echo "=== 5) 状态 ==="
curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin); p=d['policy']
print('  待批准:', p['pending'], ' 已批准:', p['approved_active'])
"
echo "=== 6) 重发完全相同的命令 ==="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/iso_test"}}' $B/tool | head -c 200; echo
echo "=== 7) 文件 ==="
ls -l /tmp/iso_test 2>&1 | head -1