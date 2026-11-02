#!/usr/bin/env bash
# =============================================================================
# compare_pp.sh —— ★ 输入表示选型实验：stft（接口②建议）vs wdens（密度图）
#
# 为什么要做这个实验：
#   接口 ② 建议用 STFT。但 STFT 要分开谐波，要求一个窗内至少有 2 个周期：
#       窗内周期数 = K × NFFT / 4096
#   而示波器为了"屏幕上显示 2~5 个周期"，缓冲区内只有 K = 2~5 个周期
#   ⇒ 窗内 0.25~0.6 个周期 ⇒ 谐波完全糊在一起。
#   密度图（时间×幅度）在少周期时直接给出波形形状，多周期时给出幅度分布，
#   两种工况下都有判别信息。
#
# 本脚本用**同一份随机种子的原始采集数据**（dataset_gen 的 raw 已全量落盘，
# 两个模式产生的 raw 逐字节相同）分别训练，用验证集/测试集比出赢家。
# =============================================================================
set -euo pipefail

PROJ=${PROJ:-/data/pengyc_fzu/fpga2026_ai}
PY=${PY:-/data/pengyc_fzu/envs/fpga2026/bin/python}
SEED=${SEED:-20261001}
N_TRAIN=${N_TRAIN:-12000}
N_VAL=${N_VAL:-1500}
N_TEST=${N_TEST:-1500}
EP_FLOAT=${EP_FLOAT:-18}
EP_QAT=${EP_QAT:-14}
DEV=${DEV:-0}

mkdir -p "$PROJ/logs" "$PROJ/runs"

cd "$PROJ/src/common"
for PP in wdens stft; do
  D="$PROJ/data/scope_ds_${PP}"
  R="$PROJ/runs/cmp_${PP}"
  echo "=============================================================="
  echo "### 输入表示 = $PP"
  echo "=============================================================="
  if [ ! -f "$D/meta.json" ]; then
    "$PY" dataset_gen.py --out "$D" --seed "$SEED" --pp "$PP" \
        --train "$N_TRAIN" --val "$N_VAL" --test "$N_TEST" --no-per-sample
  fi
  cd "$PROJ/src/train"
  "$PY" train_waveform.py --data "$D" --out "$R" --seed "$SEED" \
      --epochs-float "$EP_FLOAT" --epochs-qat "$EP_QAT" --gpu "$DEV" \
      --no-reference-eval 2>&1 | tee "$PROJ/logs/cmp_${PP}.log" | tail -n 30
  cd "$PROJ/src/common"
done

echo
echo "=========================== 结论 ==========================="
"$PY" - <<'PYEOF'
import json, os
proj = os.environ.get("PROJ", "/data/pengyc_fzu/fpga2026_ai")
rows = []
for pp in ("wdens", "stft"):
    p = os.path.join(proj, "runs", "cmp_%s" % pp, "train_report.json")
    if not os.path.exists(p):
        rows.append((pp, None, None, None)); continue
    r = json.load(open(p, encoding="utf-8"))
    f = r.get("final", {})
    rows.append((pp, f.get("test_acc_torch"), f.get("train_acc"),
                 json.dumps(f.get("mfq"))))
print("%-8s %12s %12s %16s" % ("表示", "test_acc", "train_acc", "MFQ"))
for pp, te, tr, mfq in rows:
    print("%-8s %12s %12s %16s" % (pp,
          "%.4f" % te if te is not None else "-",
          "%.4f" % tr if tr is not None else "-", mfq or "-"))
ok = [r for r in rows if r[1] is not None]
if ok:
    best = max(ok, key=lambda r: r[1])
    print("\n★ 胜出：%s  (test_acc=%.4f)" % (best[0], best[1]))
PYEOF
echo "COMPARE_DONE"
