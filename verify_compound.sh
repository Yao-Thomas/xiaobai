#!/bin/bash
B=http://127.0.0.1:8765
J='Content-Type: application/json'
echo -n "  system 工具 -> "
curl -s --max-time 40 -X POST -H "$J" -d '{"name":"system","args":{}}' $B/tool \
  | python3 -c "
import json,sys
d=json.load(sys.stdin); r=str(d.get('result') or d.get('error'))
print(r.replace(chr(10),' | ')[:150])
"
echo
echo "  再测两个边界（应该仍然被拦）："
echo -n "    ls; rm -rf /tmp/zzz  -> "
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"ls; rm -rf /tmp/zzz"}}' $B/tool \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d.get('result'))[:70])"
echo -n "    uptime; systemctl restart zynq-audio -> "
curl -s --max-time 30 -X POST -H "$J" \
  -d '{"name":"shell","args":{"cmd":"uptime; systemctl restart zynq-audio"}}' $B/tool \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d.get('result'))[:70])"
echo
echo "  清空审计留下的待批准队列："
curl -s --max-time 10 -X POST -H "$J" -d '{}' $B/pending/clear; echo