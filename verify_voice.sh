#!/bin/bash
# 验证：百度 token / TTS 合成并播放 / 桌面进程 / 截图
echo "=== 1) 百度 token + TTS 合成 + 从喇叭说出来 ==="
sudo sh -c 'set -a; . /etc/zynq-agent.env; set +a; cd /home/zynq; python3 - <<PY
import sys, time
sys.path.insert(0, "/home/zynq")
from agent import tts, audio_client as ac
print("音频服务在线:", ac.alive())
try:
    t0 = time.time()
    tok = tts.token()
    print("百度 token: 拿到 (%d 字符, %.1fs)" % (len(tok), time.time()-t0))
except Exception as e:
    print("百度 token 失败:", type(e).__name__, e); raise SystemExit(1)
try:
    t0 = time.time()
    p = tts.synth("我是系统管家小白，这块板子的系统管家。")
    import os
    print("TTS 合成: %s  %d 字节  %.1fs" % (p, os.path.getsize(p), time.time()-t0))
except Exception as e:
    print("TTS 合成失败:", type(e).__name__, e); raise SystemExit(1)
try:
    t0 = time.time()
    r = ac.play_file(p)
    print("已从喇叭播放: %s  (%.1fs)" % (r, time.time()-t0))
except Exception as e:
    print("播放失败:", type(e).__name__, e)
PY'

echo
echo "=== 2) 桌面进程 ==="
pgrep -af "desktop" | head -5
echo "--- APPS 里能不能 import apps_agent ---"
cd /home/zynq/ui && python3 -c "
import ast, io
src = io.open('apps_agent.py', encoding='utf-8').read()
ast.parse(src)
print('apps_agent.py 语法 OK')
import re
d = io.open('desktop.py', encoding='utf-8').read()
print('desktop.py 里有 icon_ai:', 'def icon_ai' in d)
print('desktop.py 里注册了 系统管家小白:', '系统管家小白' in d)
" 2>&1

echo
echo "=== 3) 截图 ==="
ls -l /tmp/*.png 2>/dev/null | tail -3
for p in /home/zynq/ui/shot.sh /home/zynq/shot.sh /home/zynq/ui/screenshot.py; do
  [ -f "$p" ] && echo "找到截图工具: $p"
done
