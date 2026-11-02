#!/bin/bash
sudo systemctl restart zynq-agent; sleep 4
systemctl is-active zynq-agent
echo "=== 用板载录音测试 asr.recognize() 统一入口 ==="
sudo python3 - <<'PY'
import sys, os
sys.path.insert(0, "/home/zynq")
# 从密钥文件补上环境变量（服务里有，交互 shell 没有）
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v
from agent import asr
print("  baidu 可用:", asr.baidu_available())
print("  vosk  可用:", asr.vosk_available())
wav = "/tmp/mic_evidence.wav"
print("  测试文件:", wav, os.path.exists(wav))
try:
    t, e = asr.recognize(wav)
    print()
    print("  ★ 引擎 =", e)
    print("  ★ 识别 =", repr(t))
except Exception as ex:
    print("  ✗ 失败:", ex)
PY