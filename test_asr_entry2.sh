#!/bin/bash
echo "=== 用板载录音测 asr.recognize() 统一入口（现在应该百度优先）==="
sudo python3 - <<'PY'
import sys, os
sys.path.insert(0, "/home/zynq")
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v
from agent import asr
wav = "/tmp/mic_evidence.wav"
print("  测试文件:", wav, os.path.exists(wav))
print("  vosk 可用:", asr.vosk_available())
try:
    t, e = asr.recognize(wav)
    print()
    print("  ★ 引擎 =", e)
    print("  ★ 识别 =", repr(t))
except Exception as ex:
    print("  ✗ 失败:", type(ex).__name__, ex)

print()
print("=== 再测 vosk 作对照（同一个文件）===")
try:
    t2, e2 = asr.recognize(wav, engine="vosk")
    print("  vosk 引擎 =", e2, " 识别 =", repr(t2))
except Exception as ex:
    print("  vosk 失败:", ex)
PY