#!/usr/bin/env bash
echo "=== 1) 有没有挂住的 aplay ==="
ps -eo pid,stat,etime,args | grep "[a]play"
echo
echo "=== 2) 谁占着声卡 ==="
ls -l /proc/*/fd 2>/dev/null | grep -c "snd" 
for p in $(ps -eo pid,args | grep "[a]play" | awk '{print $1}'); do
  echo "  PID $p 的状态: $(cat /proc/$p/status 2>/dev/null | grep -E '^(State|Name)' | tr '\n' ' ')"
  echo "    打开的 snd 设备: $(ls -l /proc/$p/fd 2>/dev/null | grep -c snd)"
done
echo
echo "=== 3) 服务报告的 last_error（完整）==="
curl -s --max-time 8 http://127.0.0.1:8767/state | python3 -c "
import json,sys
d = json.load(sys.stdin)
print('  playing =', d.get('playing'))
print('  volume  =', d.get('volume'))
print('  error   =', (d.get('last_error') or '(无)')[:400])
"
echo
echo "=== 4) 清掉挂住的进程 + 重启服务 ==="
sudo pkill -9 aplay 2>/dev/null; sleep 1
sudo systemctl restart zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 5) 现在能不能播了（放 3 秒纯音测试）==="
aplay -q /home/zynq/Music/提示音.wav
echo "  提示音退出码: $?"
