#!/usr/bin/env bash
# 量所有音乐文件的 RMS（= 实际响度），挑最响的
echo "=== 各文件的峰值 / RMS / 波峰因数 ==="
echo "  （RMS 才是耳朵感受到的响度；波峰因数 = 峰值 - RMS）"
echo
python3 - <<'PY'
import wave, struct, math, os

D = "/home/zynq/Music"
rows = []
for name in sorted(os.listdir(D)):
    if not name.lower().endswith(".wav"):
        continue
    p = os.path.join(D, name)
    if not os.path.isfile(p):
        continue
    try:
        w = wave.open(p, "rb")
        n, sw, ch, r = w.getnframes(), w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(n)
        w.close()
        if sw != 2:
            continue
        v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
        if not v:
            continue
        pk = max(abs(x) for x in v)
        rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
        pk_db = 20*math.log10(max(1e-9, pk/32767.0))
        rms_db = 20*math.log10(max(1e-9, rms/32767.0))
        rows.append((rms_db, pk_db, pk_db-rms_db, name, n/float(r)))
    except Exception:
        pass

rows.sort(reverse=True)
print("  %-24s %8s %8s %8s %7s" % ("文件", "RMS dB", "峰值dB", "波峰因数", "时长"))
print("  " + "-"*68)
for rms_db, pk_db, cf, name, secs in rows:
    star = " ★最响" if rms_db == rows[0][0] else ""
    print("  %-24s %8.1f %8.1f %8.1f %6.1fs%s"
          % (name[:24], rms_db, pk_db, cf, secs, star))
print()
print("  （RMS 越大 = 耳朵听着越响）")
PY
echo
echo "=== 顺便看：原始备份的 RMS（对比归一化前的响度）==="
python3 - <<'PY'
import wave, struct, math, os
D = "/home/zynq/Music/_原始备份"
if os.path.isdir(D):
    for name in sorted(os.listdir(D)):
        if not name.lower().endswith(".wav"):
            continue
        p = os.path.join(D, name)
        try:
            w = wave.open(p, "rb"); n, sw = w.getnframes(), w.getsampwidth()
            raw = w.readframes(n); w.close()
            v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
            pk = max(abs(x) for x in v)
            rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
            print("  %-24s RMS %6.1f dB  峰值 %6.1f dB"
                  % (name[:24], 20*math.log10(max(1e-9,rms/32767.0)),
                     20*math.log10(max(1e-9,pk/32767.0))))
        except Exception:
            pass
PY
