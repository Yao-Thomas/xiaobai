#!/bin/bash
echo "=== 装 srt / tqdm（纯 Python，不用编译）==="
sudo python3 -m pip install --no-cache-dir srt tqdm 2>&1 | tail -4
echo
echo "=== 验证 import ==="
python3 -c "import vosk; print('VOSK OK')" 2>&1 | tail -2
echo
echo "=== 用模型跑一次真实识别 ==="
cd /home/zynq
sudo python3 - <<'PY'
import sys, os, json, wave, subprocess, time
sys.path.insert(0, "/home/zynq")
# 先用 espeak 造一段"已知内容"的中文语音，再让 vosk 识别 —— 闭环自证
wav = "/tmp/asr_test.wav"
subprocess.run(["espeak-ng", "-v", "cmn", "-s", "140", "-w", wav,
                "今天天气很好，系统运行正常"], check=True)
from agent import asr
print("vosk 可用:", asr.vosk_available())
t0 = time.time()
try:
    text = asr.recognize_vosk(wav)
    print("识别结果: %r   (%.1fs)" % (text, time.time() - t0))
except Exception as e:
    import traceback; traceback.print_exc()
PY
