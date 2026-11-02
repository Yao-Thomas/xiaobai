#!/bin/bash
# 逐个审计 Agent 的 12 个工具（能静默测的都测）
B=http://127.0.0.1:8765
J='Content-Type: application/json'
call() {
  # $1=工具名  $2=args JSON  $3=说明
  printf "  %-9s %-34s " "$1" "$3"
  R=$(curl -s --max-time 40 -X POST -H "$J" \
      -d "{\"name\":\"$1\",\"args\":$2}" $B/tool)
  echo "$R" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    r=d.get('result') or d.get('error') or str(d)
except Exception as e:
    r='(解析失败) '+str(e)
r=str(r).replace(chr(10),' | ')
print(r[:96])
"
}

echo "===== Agent 工具审计 $(date '+%T') ====="
echo
echo "【应放行】"
call shell    '{"cmd":"echo AUDIT_OK"}'                       "shell 只读"
call read     '{"path":"/home/zynq/ui/audio_pl.py","limit":2}' "read 读文件"
call glob     '{"pattern":"*.py","root":"/home/zynq/ui"}'      "glob 找文件"
call grep     '{"pattern":"def codec_up","root":"/home/zynq/ui"}' "grep 搜内容"
call system   '{}'                                             "system 系统状态"
call todo     '{"items":["done|审计工具"]}'                     "todo 任务列表"
call http     '{"url":"http://127.0.0.1:8765/health","max_kb":2}' "http 抓本地"
echo
echo "【应被静音锁拒绝】"
call speak    '{"text":"审计时说一句话"}'                       "speak"
call audio    '{"action":"selftest"}'                          "audio 自检"
echo
echo "【应要求批准】"
call write    '{"path":"/etc/zynq-audit-test","content":"x"}'   "write 写 /etc"
call edit     '{"path":"/home/zynq/ui/audio_pl.py","old":"x","new":"y"}' "edit 改代码"
echo
echo "【需要音频服务，当前停着】"
printf "  %-9s %-34s " "listen" "听 2 秒"
curl -s --max-time 20 -X POST -H "$J" \
  -d '{"name":"listen","args":{"secs":2}}' $B/tool | head -c 110; echo
echo
echo "===== 权限层状态 ====="
curl -s --max-time 10 $B/pending | python3 -c "
import json,sys
d=json.load(sys.stdin); p=d['policy']
print('  静音锁:', p['silent'], ' 待批准:', p['pending'])
for it in d.get('pending',[]):
    print('    -', it['payload'][:70])
"
