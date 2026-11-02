#!/bin/sh
# deploy_cloud_api.sh —— 更新云协同服务并验证转发
echo "=== 重启 cloud-api ==="
sudo systemctl restart cloud-api
sleep 5
echo "  cloud-api: $(systemctl is-active cloud-api)"
echo
TOKEN=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['token'])" 2>/dev/null)
B="http://127.0.0.1:8768"
echo "=== ① /tools 转发（以前是"未知接口"）==="
curl -s --max-time 12 -H "Authorization: Bearer $TOKEN" "$B/tools" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('ok'):
    n=[t.get('name') if isinstance(t,dict) else str(t) for t in d.get('tools',[])]
    print('  ✓ %d 个工具（硬件 %d）' % (len(n), len([x for x in n if x.startswith('hw_')])))
else:
    print('  ✗', d.get('error'))
" 2>&1
echo
echo "=== ② POST /tool 转发 ==="
curl -s --max-time 15 -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"hw_thermal","args":{}}' "$B/tool" | head -c 200
echo
echo
echo "=== ③ POST /voice 转发 ==="
curl -s --max-time 30 -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"text":"现在多少度"}' "$B/voice" | head -c 200
echo
echo
echo "=== ④ 对照：直接打 agent 的 8765 ==="
curl -s --max-time 10 http://127.0.0.1:8765/tools | python3 -c "
import json,sys
d=json.load(sys.stdin)
n=[t.get('name') if isinstance(t,dict) else str(t) for t in d.get('tools',[])]
print('  agent 直连: %d 个' % len(n))
" 2>&1
echo
echo "=== 温度 ==="
sudo python3 /home/zynq/thermal_guard.py --once
