#!/bin/bash
# 更强的响度最大化：峰值归一化 + 强软限幅 + 再归一化
echo "=== 对比几档推力的响度提升 ==="
python3 - <<'PY'
import wave, struct, math, os

src = "/home/zynq/Music/03_小星星.wav"
w = wave.open(src, "rb")
ch, sw, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
raw = w.readframes(n); w.close()
v = list(struct.unpack("<%dh" % (len(raw)//2), raw))

def rms(x):
    return math.sqrt(sum(float(a)*a for a in x)/len(x)) if x else 0.0

r0 = rms(v)
pk0 = max(abs(x) for x in v)
print("  原始: 峰值=%d (%.1f dBFS)  RMS=%.0f (%.1f dBFS)"
      % (pk0, 20*math.log10(pk0/32767.0), r0, 20*math.log10(r0/32767.0)))
print()
print("  %-8s %-14s %-14s %s" % ("推力", "峰值dBFS", "RMS dBFS", "响度提升"))
print("  " + "-" * 56)

FULL = 32767.0
best = None
for drive in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
    # 1) 峰值归一化到 0.95
    g1 = (0.95 * FULL) / pk0
    xs = [x * g1 for x in v]
    # 2) tanh 软限幅
    denom = math.tanh(drive)
    ys = [math.tanh(drive * x / FULL) / denom for x in xs]
    # 3) 再归一化到 0.98
    pk1 = max(abs(y) for y in ys)
    g2 = (0.98 * FULL) / (pk1 * FULL) if pk1 > 0 else 1.0
    zs = [max(-32768, min(32767, int(y * FULL * g2))) for y in ys]
    pz = max(abs(z) for z in zs)
    rz = rms(zs)
    gain = 20*math.log10(rz/r0) if r0 > 0 else 0
    print("  %-8.1f %-14.1f %-14.1f %+.1f dB"
          % (drive, 20*math.log10(pz/FULL), 20*math.log10(rz/FULL), gain))
    if abs(drive - 3.0) < 0.01:
        best = zs

# 用 drive=3.0 的版本落盘
if best:
    dst = "/tmp/星星_更响.wav"
    w = wave.open(dst, "wb")
    w.setnchannels(ch); w.setsampwidth(sw); w.setframerate(r)
    w.writeframes(struct.pack("<%dh" % len(best), *best))
    w.close()
    print()
    print("  已写 %s (%d 字节, 推力=3.0)" % (dst, os.path.getsize(dst)))
    print("  ★ 注：推力越大压缩感越明显，如果听着发闷/发硬就降一档")
PY
echo
echo "=== 播放（推力 3.0 版）==="
aplay -q /tmp/星星_更响.wav
echo "  aplay 退出码: $?"
