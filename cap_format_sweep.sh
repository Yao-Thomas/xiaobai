#!/usr/bin/env bash
# 采集格式扫描：找出哪种格式能录到真实音频（录音不出声）
echo "=== 支持的格式 ==="
arecord -D hw:0,1 --dump-hw-params /dev/null 2>&1 | head -20
echo
printf "  %-14s %-8s %-8s %-12s %-12s %s\n" "格式" "声道" "结果" "峰值%" "不同取值" "判定"
echo "  --------------------------------------------------------------------------"

for fmt in S24_LE S32_LE S16_LE; do
  for ch in 2 1; do
    f=/tmp/cap_${fmt}_${ch}.wav
    rm -f $f
    arecord -q -D hw:0,1 -f $fmt -r 44100 -c $ch -d 1 $f 2>/dev/null
    if [ ! -s "$f" ]; then
      printf "  %-14s %-8s %-8s\n" "$fmt" "$ch" "打不开"
      continue
    fi
    python3 - "$f" "$fmt" "$ch" <<'PY'
import wave, sys, os
p, fmt, ch = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    w = wave.open(p, "rb")
    n, sw = w.getnframes(), w.getsampwidth()
    raw = w.readframes(n); w.close()
except Exception as e:
    print("  %-14s %-8s 读取失败 %s" % (fmt, ch, e)); raise SystemExit
if sw == 4:
    import struct
    v = list(struct.unpack("<%di" % (len(raw)//4), raw))
    FULL = 2147483647.0
    # 也看低 8 位是不是全 0（左对齐特征）
    low = sum(1 for x in v[:2000] if (x & 0xFF) != 0)
elif sw == 3:
    v = []
    for i in range(len(raw)//3):
        x = int.from_bytes(raw[3*i:3*i+3], "little")
        if x & 0x800000: x -= 0x1000000
        v.append(x)
    FULL = 8388607.0
    low = -1
elif sw == 2:
    import struct
    v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
    FULL = 32767.0
    low = -1
else:
    print("  %-14s %-8s 位宽 %d 不支持" % (fmt, ch, sw*8)); raise SystemExit
pk = max(abs(x) for x in v) if v else 0
uniq = len(set(v))
pct = pk/FULL*100
verdict = "★可能有音频" if (uniq > 5000 and pct < 95) else ("削顶/常量" if pct > 95 else "取值太少(常量?)")
extra = "" if low < 0 else " 低8位非零=%d/2000" % low
print("  %-14s %-8s %-8s %-12.1f %-12d %s%s" % (fmt, ch, "OK", pct, uniq, verdict, extra))
PY
  done
done
echo
echo "=== 用 default（plug 转换）试 ==="
rm -f /tmp/cap_def.wav
arecord -q -f S16_LE -r 16000 -c 1 -d 2 /tmp/cap_def.wav 2>&1 | head -2
echo "  退出码 $?  大小 $(stat -c%s /tmp/cap_def.wav 2>/dev/null)"
