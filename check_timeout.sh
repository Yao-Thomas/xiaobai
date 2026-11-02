#!/bin/bash
echo "=== apps_music.py 的 _post / _post_raw 定义（28-60 行）==="
sed -n '28,60p' /home/zynq/ui/apps_music.py
echo
echo "=== 模拟 App 的调用（用它的默认超时）==="
python3 - <<'PY'
import json, urllib.request, time
AUDIO_URL = "http://127.0.0.1:8767"
def _post(url, obj, timeout=8):          # 先按 8 秒试
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))
t0 = time.time()
try:
    d = _post(AUDIO_URL + "/play", {"file": "/home/zynq/Music/03_小星星.wav"}, timeout=8)
    print("  8 秒超时: OK %s  耗时 %.1f 秒" % (d, time.time()-t0))
except Exception as e:
    print("  8 秒超时: ✗ %s: %s  耗时 %.1f 秒" % (type(e).__name__, e, time.time()-t0))
PY
PY_END