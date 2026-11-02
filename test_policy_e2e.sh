#!/bin/bash
# 端到端测权限层
B=http://127.0.0.1:8765
J='Content-Type: application/json'

echo "===== 1) GET /pending（权限层状态）====="
curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin)
p=d.get('policy',{})
print('  静音锁:', p.get('silent'))
print('  规则数: 只读%d 确认%d 拒绝%d' % (p.get('readonly_rules'),p.get('confirm_rules'),p.get('deny_rules')))
print('  待批准:', p.get('pending'))
"
echo
echo "===== 2) 只读命令（应放行）====="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"uptime"}}' $B/tool | head -c 220; echo
echo
echo "===== 3) 事故里那条命令（静音锁生效，应拒绝）====="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"systemctl start zynq-audio"}}' $B/tool | head -c 300; echo
echo
echo "===== 4) 另一条会改系统的命令（应变成待批准）====="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/policy_test_file"}}' $B/tool | head -c 300; echo
echo
echo "===== 5) 看待批准队列 ====="
curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin)
for it in d.get('pending',[]):
    print('  id=%s  kind=%s  动作=%s' % (it['id'], it['kind'], it['payload']))
    print('       原因:', it['reason'])
if not d.get('pending'):
    print('  (空)')
"
echo
echo "===== 6) 同意它（id=all）====="
curl -s --max-time 10 -X POST -H "$J" -d '{"id":"all","ok":true}' $B/approve | head -c 250; echo
echo
echo "===== 7) 重试同一条命令（这次应该执行）====="
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"touch /tmp/policy_test_file"}}' $B/tool | head -c 250; echo
echo "  文件真的建了吗:"
ls -l /tmp/policy_test_file 2>&1 | head -1
echo
echo "===== 8) 确认音频服务仍被封锁 ====="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
sudo systemctl start zynq-audio 2>&1 | head -1
