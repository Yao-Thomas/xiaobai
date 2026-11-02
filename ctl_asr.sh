#!/bin/bash
cd /home/zynq
sudo python3 - <<'PY'
import sys, subprocess, time
sys.path.insert(0, "/home/zynq")
from agent import asr

print("=== 对照 A: 干净的 espeak WAV 直接喂 vosk（不走声学链路）===")
for voice in ("cmn", "zh"):
    p = "/tmp/ctl_%s.wav" % voice
    try:
        subprocess.run(["espeak-ng", "-v", voice, "-s", "120", "-w", p,
                        "现在几点"], check=True, timeout=60)
    except Exception as e:
        print("  voice=%s 合成失败: %s" % (voice, e)); continue
    t0 = time.time()
    try:
        t = asr.recognize_vosk(p)
    except Exception as e:
        print("  voice=%s 识别异常: %s" % (voice, e)); continue
    print("  voice=%-4s 识别=%r  (%.1fs)" % (voice, t, time.time()-t0))

print()
print("=== 对照 B: 板载录音 WAV（走过整条声学链路）===")
for f in ("/tmp/vs_rec.wav",):
    try:
        t = asr.recognize_vosk(f)
        print("  %s -> %r" % (f, t))
    except Exception as e:
        print("  %s 识别异常: %s" % (f, e))

print()
print("结论判据:")
print("  若 A 也认不出 -> 限制在 espeak 机器音，声学链路本身是通的")
print("  若 A 认得出而 B 认不出 -> 声学链路还有问题")
PY
