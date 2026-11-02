#!/bin/bash
# 端到端：Agent 对话 + TTS 说话 + 录音听写
echo "=== 1) 问 Agent 一个问题（走 LLM + 工具）==="
curl -s --max-time 200 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"用一句话介绍你自己，然后告诉我这块板子的 CPU 占用和内存。"}' \
  http://127.0.0.1:8765/voice > /tmp/ans.json
python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/ans.json"))
    print("轮数=%s 耗时=%ss" % (d.get("rounds"), d.get("elapsed")))
    print("回复:", (d.get("reply") or "")[:600])
except Exception as e:
    print("解析失败:", e, open("/tmp/ans.json").read()[:400])
PY

echo
echo "=== 2) TTS 合成 + 从喇叭说出来 ==="
sudo sh -c 'set -a; . /etc/zynq-agent.env; set +a; cd /home/zynq; python3 - <<PY
import sys, os, time
sys.path.insert(0, "/home/zynq")
from agent import tts, audio_client as ac
print("音频服务在线:", ac.alive())
try:
    t0=time.time(); tok = tts.token()
    print("百度 token: OK (%d 字符, %.1fs)" % (len(tok), time.time()-t0))
    t0=time.time(); p = tts.synth("你好，我是系统管家小白。")
    print("TTS 合成: %s (%d 字节, %.1fs)" % (p, os.path.getsize(p), time.time()-t0))
    t0=time.time(); r = ac.play_file(p)
    print("★ 已从板载喇叭播放: %s (%.1fs)" % (r, time.time()-t0))
except Exception as e:
    import traceback; traceback.print_exc()
PY'

echo
echo "=== 3) 工具清单 ==="
curl -s --max-time 8 http://127.0.0.1:8765/health
echo
echo "=== 4) 音频服务状态 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state
echo
