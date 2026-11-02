#!/bin/bash
# 测百度 TTS 的 vol 参数（0~15）。仍然**不播放**。
echo "===== 百度 TTS vol 扫描（只生成文件）====="
sudo python3 - <<'PY'
import os, sys, wave, math, struct, time
sys.path.insert(0, "/home/zynq")
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v
from agent import tts

TEXT = "你好，我是系统管家小白。"
def info(p):
    w = wave.open(p, "rb")
    n = w.getnframes(); d = w.readframes(n); r = w.getframerate(); w.close()
    v = struct.unpack("<%dh" % (len(d)//2), d)
    rms = math.sqrt(sum(float(x)*x for x in v)/len(v)) if v else 0
    pk = max(abs(x) for x in v) if v else 0
    return n/float(r), rms, pk

print("  %-8s %-9s %-10s %-9s %s" % ("vol", "时长", "RMS", "峰值", "相对默认(dB)"))
print("  " + "-" * 62)
base = None
for vol in (5, 8, 10, 12, 15):
    out = "/tmp/tts_vol%d.wav" % vol
    try:
        tts.synth(TEXT, out_path=out, per=0, vol=vol, engine="baidu")
        dur, rms, pk = info(out)
        if base is None:
            base = rms
        db = 20 * math.log10(max(1e-9, rms) / max(1e-9, base))
        print("  %-8d %-9.2f %-10.0f %-9d %+.1f" % (vol, dur, rms, pk, db))
    except Exception as e:
        print("  %-8d 失败: %s" % (vol, str(e)[:90]))
print()
print("  ★ 全程没有播放，只生成了文件")
PY
echo
systemctl is-active zynq-audio
