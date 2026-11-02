#!/bin/bash
# 扫放音电平，找"边放边录不自激"的线性区
#
# 背景：/matrix 默认 amp=0.9（很响）。边放边录时 ADC 输入过载，
#       采到的是整片抬平的噪声（平坦度 ~1.5），不是纯音（应该 ~1e5）。
#       第四轮就是这个现象，当时判据 >1.8 识别不出来。
#
# 这里从很轻开始逐级加，看哪一级开始出现"平坦度 >100 的对角线"。
echo "=== 放音电平扫描（找 ③ 能成立的线性区）==="
echo "判据: 对角线命中>=5/6 且 最小平坦度>100"
echo
printf "%-8s %-10s %-12s %-9s %s\n" "amp" "命中" "最小平坦度" "结论" "备注"
echo "--------------------------------------------------------------------------"
for amp in 0.05 0.08 0.12 0.18 0.25 0.35 0.50 0.70 0.90; do
  R=$(curl -s --max-time 200 -X POST -H 'Content-Type: application/json' \
      -d "{\"secs\":0.45,\"amp\":$amp}" http://127.0.0.1:8767/matrix)
  echo "$R" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('  amp=$amp  解析失败'); raise SystemExit
hit = d.get('hit', 0); tot = d.get('total', 6)
mf  = d.get('min_flatness', 0.0)
ok  = d.get('pass', False)
note = ''
if mf > 100 and hit >= tot - 1: note = '★ 线性区，③ 可成立'
elif mf > 100:                  note = '有纯音但命中不够'
elif mf < 10:                   note = '过载/噪声'
else:                           note = '临界'
print('%-8s %-10s %-12.1f %-9s %s' % ('$amp', '%d/%d' % (hit, tot), mf,
                                      '通过' if ok else '不通过', note))
"
done
echo "--------------------------------------------------------------------------"
echo "读数说明："
echo "  平坦度 ~1e5  = 真采到了纯音（对角线会很明显）"
echo "  平坦度 ~1.5  = 白噪声（过载把频谱抬平了）"
echo "  从低到高，平坦度突然掉下来的那一级 就是过载临界点"
