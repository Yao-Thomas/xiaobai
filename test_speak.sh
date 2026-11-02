#!/bin/bash
B=http://127.0.0.1:8765
A=http://127.0.0.1:8767

echo "=== 播放计数（说话前）==="
curl -s --max-time 8 $A/state; echo

echo
echo "=== 让 Agent 用它自己的 speak 工具说话 ==="
curl -s --max-time 240 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"请先用 speak 工具从喇叭说一句：你好，我是系统管家小白，板载语音链路已经打通。说完再用一句话告诉我你刚才做了什么。"}' \
  $B/voice > /tmp/sp.json
python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/sp.json"))
    print("轮数=%s 耗时=%ss" % (d.get("rounds"), d.get("elapsed")))
    print("回复:", (d.get("reply") or "")[:700])
except Exception as e:
    print("解析失败:", e, open("/tmp/sp.json").read()[:400])
PY

echo
echo "=== 播放计数（说话后，应该变大了）==="
curl -s --max-time 8 $A/state; echo

echo
echo "=== Agent 服务日志尾部 ==="
sudo journalctl -u zynq-agent --no-pager -n 20 2>&1 | tail -20
