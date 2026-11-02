#!/bin/bash
# 麦克风通路检查（第一步）—— 不放音，只看通路活不活
echo "===== 1) 音频服务 ====="
systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "===== 2) ADC 存活 + 静音基线（不放音，只录环境声）====="
python3 - <<'PY'
import json, math, struct, sys, time, urllib.request, io, wave
sys.path.insert(0, "/home/zynq/ui")
AUDIO = "http://127.0.0.1:8767"

def rec(secs, rate=16000, mono=True):
    req = urllib.request.Request(
        AUDIO + "/record",
        data=json.dumps({"secs": secs, "rate": rate, "mono": mono}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()

def analyze(b, tag):
    w = wave.open(io.BytesIO(b), "rb")
    n = w.getnframes()
    d = w.readframes(n)
    v = struct.unpack("<%dh" % (len(d) // 2), d)
    if not v:
        print("  %-10s 没采到数据" % tag)
        return None
    rms = math.sqrt(sum(float(x) * x for x in v) / len(v))
    pk = max(abs(x) for x in v)
    nz = sum(1 for x in v if abs(x) > 6) / float(len(v))   # 非零样点比例
    print("  %-10s 帧=%-7d RMS=%-9.1f 峰值=%-7d 非零占比=%.1f%%  时长=%.2fs"
          % (tag, n, rms, pk, nz * 100, n / float(w.getframerate())))
    return rms, pk, nz

print("  连录 4 次（每次 1.5 秒，中间不停），看稳定性:")
vals = []
for i in range(4):
    try:
        b = rec(1.5)
        r = analyze(b, "第%d次" % (i + 1))
        if r:
            vals.append(r)
    except Exception as e:
        print("  第%d次 失败: %s" % (i + 1, e))
    time.sleep(0.4)

if len(vals) >= 2:
    rms_l = [v[0] for v in vals]
    spread = max(rms_l) / max(1e-9, min(rms_l))
    print()
    print("  RMS 波动比 (max/min) = %.2f  -> %.1f dB"
          % (spread, 20 * math.log10(max(1e-9, spread))))
    print("  —— 判读：<2 倍(6dB) 算稳；>10 倍(20dB) 就是那个'30dB 波动'的老问题")
PY
echo
echo "===== 3) 麦克风的物理位置提示 ====="
echo "  板载麦克风在板子背面（见 硬件资料/装配图_音频接口位置.png）"
echo "  说话时对准它，距离 10~20cm 效果最好"
