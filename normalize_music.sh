#!/usr/bin/env bash
# 把音乐目录里所有 WAV 做温和的峰值归一化（不用重压缩，避免听感发闷）
# 原始文件先备份到 Music/_原始备份/
set -e
cd /home/zynq/Music || exit 1
mkdir -p _原始备份

echo "=== 处理前后对比 ==="
printf "  %-28s %-10s %-10s %s\n" "文件" "原峰值dB" "新峰值dB" "增益"
echo "  ------------------------------------------------------------------"

python3 - <<'PY'
import wave, struct, math, os, shutil

D = "/home/zynq/Music"
BAK = os.path.join(D, "_原始备份")
TARGET = int(0.95 * 32767)          # -0.45 dBFS
MAXGAIN = 6.0                       # 最多放大 6 倍(15.6dB)，避免把噪声抬起来

for name in sorted(os.listdir(D)):
    if not name.lower().endswith(".wav"):
        continue
    src = os.path.join(D, name)
    if not os.path.isfile(src):
        continue
    try:
        w = wave.open(src, "rb")
        ch, sw, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
        w.close()
        if sw != 2:
            print("  %-28s (位宽 %dbit，跳过)" % (name[:28], sw*8))
            continue
        v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
        pk = max(abs(x) for x in v) if v else 0
        if pk == 0:
            print("  %-28s (全静音，跳过)" % name[:28])
            continue
        g = TARGET / float(pk)
        if g > MAXGAIN:
            g = MAXGAIN
        pk_db = 20*math.log10(pk/32767.0)
        if g <= 1.02:
            print("  %-28s %8.1f  %8.1f   已够大，不动" % (name[:28], pk_db, pk_db))
            continue
        # 备份
        bak = os.path.join(BAK, name)
        if not os.path.exists(bak):
            shutil.copy2(src, bak)
        out = [max(-32768, min(32767, int(x * g))) for x in v]
        nw = wave.open(src, "wb")
        nw.setnchannels(ch); nw.setsampwidth(sw); nw.setframerate(r)
        nw.writeframes(struct.pack("<%dh" % len(out), *out))
        nw.close()
        npk = max(abs(x) for x in out)
        print("  %-28s %8.1f  %8.1f   %+.1f dB"
              % (name[:28], pk_db, 20*math.log10(npk/32767.0), 20*math.log10(g)))
    except Exception as e:
        print("  %-28s 失败: %s" % (name[:28], e))
PY
echo
echo "=== 备份目录 ==="
ls -1 _原始备份/ 2>/dev/null | head -12 | sed 's/^/  /'
echo
echo "=== 处理后目录 ==="
ls -l *.wav | awk '{print "  "$5"  "$9}'
