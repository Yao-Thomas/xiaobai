#!/bin/bash
# 把百度密钥部署到板子，并在板上实测语音识别
set -u
echo "===== 1) 写入密钥文件 ====="
sudo tee /etc/zynq-baidu.env > /dev/null <<'EOF'
BAIDU_API_KEY=YOUR_BAIDU_KEY_HERE
BAIDU_SECRET_KEY=YOUR_BAIDU_KEY_HERE
EOF
sudo chmod 600 /etc/zynq-baidu.env
sudo chown root:root /etc/zynq-baidu.env
ls -l /etc/zynq-baidu.env

echo
echo "===== 2) 让 zynq-agent 服务带上这两个环境变量 ====="
UNIT=/etc/systemd/system/zynq-agent.service
if [ -f "$UNIT" ]; then
  if ! grep -q "zynq-baidu.env" "$UNIT"; then
    sudo sed -i "/\[Service\]/a EnvironmentFile=-/etc/zynq-baidu.env" "$UNIT"
    echo "  已加入 EnvironmentFile"
  else
    echo "  已经有了"
  fi
  grep -nE "EnvironmentFile|ExecStart|After" "$UNIT"
  sudo systemctl daemon-reload
  sudo systemctl restart zynq-agent
  sleep 4
  echo "  zynq-agent: $(systemctl is-active zynq-agent)"
else
  echo "  找不到 $UNIT"
fi

echo
echo "===== 3) 板上实测：拿刚才那段真机录音打百度 ASR ====="
python3 - <<'PY'
import base64, json, os, sys, urllib.parse, urllib.request, wave
sys.path.insert(0, "/home/zynq/ui")
AK = os.environ.get("BAIDU_API_KEY", "")
SK = os.environ.get("BAIDU_SECRET_KEY", "")
print("  AK 长度 %d   SK 长度 %d" % (len(AK), len(SK)))
if not AK or not SK:
    # 服务里取不到就从文件读
    for line in open("/etc/zynq-baidu.env"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            if k == "BAIDU_API_KEY": AK = v
            if k == "BAIDU_SECRET_KEY": SK = v
    print("  （从 /etc/zynq-baidu.env 读的）AK %d SK %d" % (len(AK), len(SK)))

u = "https://aip.baidubce.com/oauth/2.0/token?" + urllib.parse.urlencode({
    "grant_type": "client_credentials", "client_id": AK, "client_secret": SK})
tok = json.loads(urllib.request.urlopen(u, timeout=20).read().decode())
if "access_token" not in tok:
    print("  ✗ 换 token 失败:", json.dumps(tok, ensure_ascii=False)[:200])
    raise SystemExit(1)
print("  ✓ 板上换到 token:", tok["access_token"][:20], "...")

# 用板上录的那段
wav = "/tmp/mic_evidence.wav"
if not os.path.exists(wav):
    cands = [p for p in os.listdir("/tmp/mic_chunks") if p.endswith(".wav")]
    if cands:
        cands.sort()
        wav = "/tmp/mic_chunks/" + cands[len(cands)//2]
if not os.path.exists(wav):
    print("  ✗ 没有测试录音 %s" % wav); raise SystemExit(1)

w = wave.open(wav, "rb")
d = w.readframes(w.getnframes())
rate, ch = w.getframerate(), w.getnchannels()
w.close()
print("  录音: %s  %d Hz %d 声道 %d 字节" % (os.path.basename(wav), rate, ch, len(d)))

body = {"format": "pcm", "rate": rate, "channel": ch, "cuid": "zynq-board",
        "token": tok["access_token"],
        "speech": base64.b64encode(d).decode(), "len": len(d)}
req = urllib.request.Request("https://vop.baidu.com/server_api",
                             data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
res = json.loads(urllib.request.urlopen(req, timeout=40).read().decode())
print("  百度返回:", json.dumps(res, ensure_ascii=False)[:300])
if res.get("err_no") == 0:
    print()
    print("  ★★★ 板上识别成功:", res.get("result"))
else:
    print("  ✗ err_no=%s %s" % (res.get("err_no"), res.get("err_msg")))
PY
