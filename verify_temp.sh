#!/bin/bash
sudo systemctl restart zynq-agent; sleep 5
echo -n "zynq-agent: "; systemctl is-active zynq-agent
echo
echo "--- /status 里的系统信息 ---"
curl -s --max-time 15 http://127.0.0.1:8765/status | python3 -c "
import json,sys
d=json.load(sys.stdin)
for k,v in d.get('system',{}).items():
    print('  %-14s %s' % (k, v))
"