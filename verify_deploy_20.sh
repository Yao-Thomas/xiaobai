#!/bin/bash
# 板上语法 + 逻辑自检（不出声，不启动音频服务）
cd /home/zynq/ui || exit 1
echo "=== 语法 ==="
for f in matrix_vol.py audio_svc.py policy.py; do
  python3 -c "
import ast, io, sys
try:
    ast.parse(io.open('$f', encoding='utf-8').read())
    print('  OK   $f')
except SyntaxError as e:
    print('  FAIL $f ->', e)
"
done
echo
echo "=== matrix_vol.py 的关键改动在不在 ==="
grep -n "RETRY = " matrix_vol.py
grep -n "def grab_energy" matrix_vol.py
grep -n "return hit, mn, rows" matrix_vol.py
grep -n "for f0, top, ok, pk, bs, z, valid in rows" matrix_vol.py
grep -n "故障B统计" matrix_vol.py
echo
echo "=== audio_svc.py 的关键改动在不在 ==="
grep -n '"valid": valid' audio_svc.py
grep -n "vrows = " audio_svc.py
grep -n "zero_captures" audio_svc.py
echo
echo "=== 逻辑自检：无效行不会被算成命中 ==="
python3 - <<'PY'
FREQS = [495.3, 646.0, 990.5, 1292.0, 1507.3, 2002.6]
def judge(e, f0):
    valid = max(e) > 0
    top = e.index(max(e)) if valid else -1
    return bool(valid and top == FREQS.index(f0))
print("  纯音(495.3):", judge([100.0,5,3,2,1,1], 495.3), " <- 期望 True")
print("  全零(495.3):", judge([0.0]*6, 495.3), " <- 期望 False")
print("  全零(1292):", judge([0.0]*6, 1292.0), " <- 期望 False")
PY
echo
echo "=== 确认没出声 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
