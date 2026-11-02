#!/bin/bash
# 测试 Agent 新增的 API
B=http://127.0.0.1:8765
echo "===== 1) GET / （接口清单）====="
curl -s --max-time 10 $B/ | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  服务:', d.get('service'), ' 端口:', d.get('port'))
for e in d.get('endpoints', []):
    print('   %-5s %-24s %s' % (e['method'], e['path'], e['desc']))
"
echo
echo "===== 2) GET /status ====="
curl -s --max-time 20 $B/status | python3 -m json.tool --no-ensure-ascii 2>/dev/null | head -32
echo
echo "===== 3) GET /tools ====="
curl -s --max-time 10 $B/tools | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  共 %d 个工具:' % d.get('count',0))
for t in d.get('tools', []):
    print('   %-9s %s' % (t['name'], (t.get('description') or '')[:58]))
"
echo
echo "===== 4) POST /tts（文字 -> 音频 base64）====="
curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"你好，我是系统管家小白，API 已经扩展好了。"}' $B/tts | python3 -c "
import json,sys,base64
d=json.load(sys.stdin)
if d.get('ok'):
    a=base64.b64decode(d['audio'])
    print('  OK  %s  %d 字节  音频 base64 %d 字符' % (d['path'], d['bytes'], len(d['audio'])))
    print('  前 12 字节 (RIFF):', a[:12])
else:
    print('  失败:', d)
"
echo
echo "===== 5) POST /asr（用已有的真机录音）====="
curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/tmp/mic_evidence.wav"}' $B/asr | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  ok=%s 引擎=%s 耗时=%s' % (d.get('ok'), d.get('engine'), d.get('elapsed')))
print('  识别:', repr(d.get('text') or d.get('error')))
"
echo
echo "===== 6) GET /history ====="
curl -s --max-time 10 $B/history | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  条数:', d.get('count'), ' 错误:', d.get('error'))
"
echo
echo "===== 7) POST /audio（查状态）====="
curl -s --max-time 15 -X POST -H 'Content-Type: application/json' \
  -d '{"action":"state"}' $B/audio | head -c 260; echo
echo
echo "===== 8) 确认音频服务仍然停着（没出声）====="
systemctl is-active zynq-audio
