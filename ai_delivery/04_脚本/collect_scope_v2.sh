#!/usr/bin/env bash
# collect_scope_v2.sh —— 等示波器策略加长训练（200 万步）跑完后，验收 + 量化 + 取回
# 用法（在 lab415 上）：bash scripts/collect_scope_v2.sh
PROJ=/data/pengyc_fzu/fpga2026_ai
PY=/data/pengyc_fzu/envs/fpga2026/bin/python
LOG=$PROJ/logs/rl_scope_long.log

echo "=== 等待训练结束 ==="
for i in $(seq 1 720); do
  grep -q SCOPE_LONG_DONE "$LOG" 2>/dev/null && break
  sleep 30
done
grep -q SCOPE_LONG_DONE "$LOG" || { echo "!! 还没结束（等了 6 小时）"; exit 1; }

echo "=== 验收结果 ==="
sed -n '/验收/,$p' "$LOG" | head -n 40
cat "$PROJ/runs/scope_policy_v2/acceptance.json" 2>/dev/null | head -n 60

echo
echo "=== 量化导出（含强制自检）==="
cd "$PROJ/src/rl"
"$PY" quantize_policy.py --model "$PROJ/runs/scope_policy_v2" \
    --out "$PROJ/deliverables/scope_policy_v2_quantized" 2>&1 | tail -n 15

echo
echo "=== 对比 v1 / v2 ==="
"$PY" - <<'PYEOF'
import json, os
for tag in ("scope_policy_v1", "scope_policy_v2"):
    p = "/data/pengyc_fzu/fpga2026_ai/runs/%s/acceptance.json" % tag
    if not os.path.exists(p):
        print(tag, "无验收文件"); continue
    d = json.load(open(p, encoding="utf-8"))
    res = d.get("results", [])
    print("%-18s 成功率: %s" % (tag, "  ".join(
        "%s=%.2f" % (r["wave"], r["success_rate"]) for r in res)))
PYEOF
echo "COLLECT_SCOPE_V2_DONE"
