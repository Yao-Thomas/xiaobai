#!/bin/bash
sudo python3 - <<'PY'
import base64, glob, json, os, ssl, urllib.parse, urllib.request, wave

# ★ 板子上的 SSL 证书链不全，urllib 会 CERTIFICATE_VERIFY_FAILED。
#   官方 curl 能通是因为它自带 CA 包。这里按 agent/tts.py 的做法降级。
CTX = ssl._create_unverified_context()

def get(url, timeout=20):
    return urllib.request.urlopen(url, timeout=timeout, context=CTX).read()

AK = SK = ""
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        if k == "BAIDU_API_KEY": AK = v
        if k == "BAIDU_SECRET_KEY": SK = v
print("  AK %d  SK %d" % (len(AK), len(SK)))

u = "https://aip.baidubce.com/oauth/2.0/token?" + urllib.parse.urlencode({
    "grant_type": "client_credentials", "client_id": AK, "client_secret": SK})
tok = json.loads(get(u))
print("  ✓ 板上换到 token:", tok["access_token"][:20], "...")

wav = "/tmp/mic_evidence.wav"
if not os.path.exists(wav):
    c = sorted(glob.glob("/tmp/mic_chunks/*.wav"))
    wav = c[len(c)//2] if c else None
w = wave.open(wav, "rb"); d = w.readframes(w.getnframes())
rate, ch = w.getframerate(), w.getnchannels(); w.close()
print("  录音 %s : %d Hz %d 声道 %d 字节" % (os.path.basename(wav), rate, ch, len(d)))

body = {"format": "pcm", "rate": rate, "channel": ch, "cuid": "zynq-board",
        "token": tok["access_token"],
        "speech": base64.b64encode(d).decode(), "len": len(d)}
req = urllib.request.Request("https://vop.baidu.com/server_api",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
res = json.loads(urllib.request.urlopen(req, timeout=40, context=CTX).read().decode())
print("  百度返回:", json.dumps(res, ensure_ascii=False)[:300])
if res.get("err_no") == 0:
    print()
    print("  ★★★ 板上识别成功:", res.get("result"))
else:
    print("  ✗", res.get("err_no"), res.get("err_msg"))
PY