#!/bin/bash
# ⑤ 语音闭环 —— **无声**验证（用已录好的真机人声，不碰麦克风和喇叭）
#
# 链条： WAV(真机录音) -> 百度ASR -> 板载Agent -> 百度TTS(写文件)
#         ↑ 这两步要用户在场        ↑ 这一步要用户同意
#
# 全程不需要音频服务，不会出声。
echo "===== ⑤ 语音闭环 · 无声验证 ====="
echo "输入用已有的真机录音；跳过实时麦克风和最后播放"
echo

sudo python3 - <<'PY'
import json, os, sys, ssl, time, urllib.request, wave
sys.path.insert(0, "/home/zynq")
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v

from agent import asr, tts

CTX = ssl._create_unverified_context()
WAV = "/tmp/mic_evidence.wav"

print("=" * 68)
print("① 输入（真机录音，替代'实时麦克风'）")
print("=" * 68)
if not os.path.exists(WAV):
    print("  ✗ 找不到", WAV)
    raise SystemExit(1)
w = wave.open(WAV, "rb")
print("  %s  %d Hz %d 声道 %.2f 秒"
      % (WAV, w.getframerate(), w.getnchannels(),
         w.getnframes() / float(w.getframerate())))
w.close()

print()
print("=" * 68)
print("② 百度 ASR（麦克风 -> 文字）")
print("=" * 68)
t0 = time.time()
try:
    text, engine = asr.recognize(WAV)
    print("  引擎: %s   耗时 %.2f 秒" % (engine, time.time() - t0))
    print("  文字: %r" % text)
except Exception as e:
    print("  ✗ 失败:", e)
    raise SystemExit(1)

if not text.strip():
    print("  （识别为空，结束）")
    raise SystemExit(0)

print()
print("=" * 68)
print("③ 板载 Agent 对话（文字 -> 回复）")
print("=" * 68)
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8765/voice",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=180, context=CTX)
    res = json.loads(r.read().decode())
    reply = res.get("reply") or ""
    print("  耗时 %.1f 秒   轮数 %s" % (time.time() - t0, res.get("rounds")))
    print("  回复: %r" % (reply[:300] if reply else reply))
except Exception as e:
    print("  ✗ Agent 失败:", e)
    reply = ""

if not reply.strip():
    print("  （没有回复，结束）")
    raise SystemExit(0)

print()
print("=" * 68)
print("④ 百度 TTS（回复 -> 音频文件，不播放）")
print("=" * 68)
try:
    t0 = time.time()
    out = tts.synth(reply)
    w = wave.open(out, "rb")
    import struct, math
    d = w.readframes(w.getnframes())
    v = struct.unpack("<%dh" % (len(d)//2), d)
    rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
    pk = max(abs(x) for x in v)
    print("  %s" % out)
    print("  %d Hz  %.2f 秒  RMS=%.0f  峰值=%d  耗时 %.2f 秒"
          % (w.getframerate(), w.getnframes()/float(w.getframerate()),
             rms, pk, time.time() - t0))
    w.close()
except Exception as e:
    print("  ✗ TTS 失败:", e)

print()
print("=" * 68)
print("⑤ 从喇叭说出来 —— **跳过**（等用户同意）")
print("=" * 68)
print("  把上一步的文件送到 /play 就完成了。现在没做。")

print()
print("=" * 68)
print("结论：链条的 4 个环节里，① 用录音替代、④ 只生成文件，")
print("      全程无声。剩下两步（实时麦克风、喇叭播放）需要用户在场。")
print("=" * 68)
PY

echo
echo "--- 确认音频服务仍然停着 ---"
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  静音锁    : "; [ -f /etc/zynq-silent ] && echo 生效 || echo 无
