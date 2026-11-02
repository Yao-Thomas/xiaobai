#!/bin/bash
sudo systemctl restart zynq-agent; sleep 4
systemctl is-active zynq-agent
sudo python3 - <<'PY'
import os, sys, wave, math, struct, time
sys.path.insert(0, "/home/zynq")
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v
from agent import tts, asr

TEXT = "你好，我是系统管家小白。现在可以听见我说话了吗？"
print("  合成:", TEXT)
t0 = time.time()
p = tts.synth(TEXT)                      # engine=None -> auto
dt = time.time() - t0
w = wave.open(p, "rb"); n = w.getnframes(); d = w.readframes(n)
r = w.getframerate(); w.close()
v = struct.unpack("<%dh" % (len(d)//2), d)
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
pk = max(abs(x) for x in v)
print("  auto 走的是: %s" % ("百度（如果峰值 ~25000）" if pk > 20000 else "espeak（峰值 ~32000）"))
print("  耗时 %.1f 秒  %d Hz  %.2f 秒  RMS=%.0f  峰值=%d" % (dt, r, n/float(r), rms, pk))
print()
print("  ★ 没有播放，只生成了文件:", p)
PY
echo -n "  zynq-audio 仍是: "; systemctl is-active zynq-audio