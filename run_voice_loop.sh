#!/bin/bash
# run_voice_loop.sh —— ⑤ 板载语音闭环的**完整**测试
#
#  麦克风 -> 百度ASR -> 板载Agent -> 百度TTS -> 喇叭
#
# ★★ 会出声！ 用法：
#      bash run_voice_loop.sh            # 完整跑（最后一步会从喇叭说出来）
#      bash run_voice_loop.sh --silent   # 只跑到"生成 TTS 音频文件"，不播放
#
# 2026-09-28 状态：除最后播放外，全部环节已在板上验证通过
set -u
MODE="${1:-}"

echo "===== 板载语音闭环 $(date '+%T')  模式=${MODE:-有声} ====="

# 1) 确保音频服务在跑（要录音，也要放音）
if [ "$MODE" != "--silent" ]; then
  echo "--- 启动音频服务（会出声，请确认旁边没人）---"
  systemctl start zynq-audio
  sleep 3
fi
echo -n "zynq-audio: "; systemctl is-active zynq-audio
echo -n "zynq-agent: "; systemctl is-active zynq-agent

sudo python3 - "$MODE" <<'PY'
import json, os, sys, time
sys.path.insert(0, "/home/zynq")
MODE = sys.argv[1] if len(sys.argv) > 1 else ""
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v
from agent import asr, tts

print()
print("=" * 70)
print("① 录音（对着麦克风说话，3 秒）")
print("=" * 70)
try:
    wav = tts.listen(3.0)          # 录 3 秒 -> /tmp/xiaobai_heard.wav
    print("   录到:", wav, os.path.getsize(wav), "字节")
except Exception as e:
    print("   ✗ 录音失败:", e)
    raise SystemExit(1)

print()
print("=" * 70)
print("② 语音识别（百度优先，vosk 兜底）")
print("=" * 70)
try:
    text, engine = asr.recognize(wav)
    print("   引擎:", engine)
    print("   文字:", repr(text))
except Exception as e:
    print("   ✗ 识别失败:", e)
    raise SystemExit(1)

if not text.strip():
    print("   （没听清，结束）")
    raise SystemExit(0)

print()
print("=" * 70)
print("③ 问板载 Agent")
print("=" * 70)
try:
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:8765/voice",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"})
    import ssl
    r = urllib.request.urlopen(req, timeout=180,
                              context=ssl._create_unverified_context())
    res = json.loads(r.read().decode())
    reply = res.get("reply") or res.get("text") or str(res)[:200]
    print("   小白:", reply)
except Exception as e:
    print("   ✗ Agent 失败:", e)
    reply = "（Agent 没有回话）"

print()
print("=" * 70)
print("④ 语音合成（百度 TTS，vol=15）")
print("=" * 70)
try:
    out = tts.synth(reply)
    import wave
    w = wave.open(out, "rb")
    print("   %s  %d Hz  %.2f 秒" % (out, w.getframerate(),
                                     w.getnframes() / float(w.getframerate())))
    w.close()
except Exception as e:
    print("   ✗ 合成失败:", e)
    out = None

print()
print("=" * 70)
print("⑤ 从喇叭说出来")
print("=" * 70)
if MODE == "--silent":
    print("   [--silent 模式] 跳过播放。音频已生成:", out)
    print("   ★ 全程无声")
else:
    if out:
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://127.0.0.1:8767/play",
                data=json.dumps({"file": out}).encode(),
                headers={"Content-Type": "application/json"})
            import ssl
            urllib.request.urlopen(req, timeout=120,
                                   context=ssl._create_unverified_context())
            print("   已送到音频服务播放:", out)
        except Exception as e:
            print("   ✗ 播放失败:", e)
    else:
        print("   没有音频可放")

print()
print("===== 闭环结束 =====")
PY
