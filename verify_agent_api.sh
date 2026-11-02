#!/bin/bash
B=http://127.0.0.1:8765
echo "===== /tools（现在应该显示真实描述了）====="
curl -s --max-time 10 $B/tools | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  共 %d 个工具:' % d['count'])
for t in d['tools']:
    ps = ','.join(t.get('params') or [])[:40]
    print('   %-9s %-52s [%s]' % (t['name'], t['description'][:52], ps))
"
echo
echo "===== /status（温度应该有了）====="
curl -s --max-time 20 $B/status | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  服务:', d['services'])
print('  系统:', d['system'])
print('  ASR :', d.get('asr'))
print('  TTS :', d.get('tts'))
"
echo
echo "===== 确认没出声 ====="
systemctl is-active zynq-audio