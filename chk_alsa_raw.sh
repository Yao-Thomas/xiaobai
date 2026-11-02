cd /home/zynq
for f in /tmp/alsa_before.raw /tmp/alsa_after.raw; do
  echo "=== $f ==="
  ls -la $f 2>/dev/null | awk '{print "  大小:", $5}'
  # 把 raw 当 24 位立体声分析（用 analyze_wav 不支持 raw，自己算）
  sudo python3 - <<PYEOF
import array, math
p = "$f"
try:
    raw = open(p,'rb').read()
except Exception as e:
    print("  读失败:", e); raise SystemExit
a = array.array("i"); a.frombytes(raw[:len(raw)&~3])
for i in range(len(a)):
    if a[i] >= 0x800000: a[i] -= 0x1000000
n = len(a)//2
L = a[0::2]; R = a[1::2]
for name, xs in (("L", L), ("R", R)):
    if not xs: continue
    rms = math.sqrt(sum(float(x)*x for x in xs)/len(xs))
    db = 20*math.log10(rms/8388608.0) if rms>0 else -999
    mx = max(xs); mn = min(xs)
    uniq = len(set(xs))
    print("  %s: 样本=%d RMS=%.0f (%.1f dBFS) min=%d max=%d 唯一值=%d" %
          (name, len(xs), rms, db, mn, mx, uniq))
    print("     均值=%.1f  前8个=%s" % (sum(xs)/len(xs), xs[:8]))
PYEOF
  echo
done