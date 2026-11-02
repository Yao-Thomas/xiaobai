#!/bin/bash
echo "=== 1) env 里密钥的长度（不回显内容）==="
sudo sh -c 'sed -n "s/^\(BAIDU_[A-Z_]*\)=\(.*\)/\1 长度=\2/p" /etc/zynq-agent.env | \
  awk -F"长度=" "{print \$1 \"长度=\" length(\$2)}"'

echo
echo "=== 2) ESP 源码里的长度 ==="
L=/home/zynq/ui/mic_beep_proof.py
if [ -f /tmp/esp_main.cpp ]; then
  grep -n "BAIDU_" /tmp/esp_main.cpp | sed 's/"[^"]*"/"<...>"/'
else
  echo "(没有 /tmp/esp_main.cpp)"
fi

echo
echo "=== 3) 有没有离线 TTS ==="
for b in espeak espeak-ng flite pico2wave festival say; do
  p=$(command -v $b 2>/dev/null); [ -n "$p" ] && echo "  有: $p"
done
echo "  (以上为空表示都没装)"
echo "--- apt 里能装吗 ---"
apt-cache policy espeak-ng 2>/dev/null | head -4

echo
echo "=== 4) 直接用 env 里的密钥试一次 token ==="
sudo sh -c 'set -a; . /etc/zynq-agent.env; set +a; python3 - <<PY
import ssl, urllib.request, urllib.parse, json
k=__import__("os").environ.get("BAIDU_API_KEY","")
s=__import__("os").environ.get("BAIDU_SECRET_KEY","")
print("key 长度=%d secret 长度=%d" % (len(k), len(s)))
q=urllib.parse.urlencode({"grant_type":"client_credentials","client_id":k,"client_secret":s})
try:
    with urllib.request.urlopen("https://aip.baidubce.com/oauth/2.0/token?"+q,
                                timeout=20, context=ssl._create_unverified_context()) as r:
        print("OK:", r.read()[:160])
except Exception as e:
    body = getattr(e, "read", lambda: b"")()
    print("失败:", type(e).__name__, e)
    if body: print("  响应体:", body[:300])
PY'
