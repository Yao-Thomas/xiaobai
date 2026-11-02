#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh —— 任务 B/C/F 一键端到端（在 lab415 上跑）
#   [1] 生成数据集（接口 ② 格式）
#   [2] 训练模型②（浮点预训练 → 量化校准 → 硬件同构 QAT）
#   [3] 评估 + 导出 quantized_model/（含 reference_in/out 与强制自检）
#
# 用法：
#   bash scripts/run_pipeline.sh                # 默认规模
#   SMOKE=1 bash scripts/run_pipeline.sh        # 冒烟测试（小数据 2 epoch）
# =============================================================================
set -euo pipefail

PROJ=${PROJ:-/data/pengyc_fzu/fpga2026_ai}
PY=${PY:-/data/pengyc_fzu/envs/fpga2026/bin/python}
DATA=${DATA:-$PROJ/data/scope_ds_v1}
RUNS=${RUNS:-$PROJ/runs}
RUN=${RUN:-$RUNS/wavenet_v1}
DELIV=${DELIV:-$PROJ/deliverables}
SEED=${SEED:-20261001}

mkdir -p "$RUNS" "$DELIV" "$PROJ/logs"

if [ "${SMOKE:-0}" = "1" ]; then
  N_TRAIN=900; N_VAL=180; N_TEST=180
  EP_FLOAT=2; EP_QAT=2; LIMIT=900; REF_EVAL="--no-reference-eval"
  DATA=$PROJ/data/scope_ds_smoke
  RUN=$RUNS/wavenet_smoke
  echo "### SMOKE 模式 ###"
else
  N_TRAIN=20000; N_VAL=2000; N_TEST=2000
  EP_FLOAT=40; EP_QAT=30; LIMIT=0; REF_EVAL=""
fi

echo "=============================================================="
echo " PROJ=$PROJ"
echo " PY=$PY"
echo " DATA=$DATA"
echo " RUN=$RUN"
echo "=============================================================="
"$PY" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.device_count())"

# ---------------------------------------------------------------- [1] 数据集
if [ -f "$DATA/meta.json" ] && [ "${FORCE_DATA:-0}" != "1" ]; then
  echo "### [1/3] 数据集已存在，跳过（FORCE_DATA=1 可强制重建）"
else
  echo "### [1/3] 生成数据集 ($N_TRAIN/$N_VAL/$N_TEST) ..."
  cd "$PROJ/src/common"
  "$PY" dataset_gen.py --out "$DATA" --seed "$SEED" \
      --train "$N_TRAIN" --val "$N_VAL" --test "$N_TEST" \
      ${SMOKE:+--no-per-sample}
  echo "--- meta.json ---"
  "$PY" -c "import json;m=json.load(open('$DATA/meta.json'));print(json.dumps({k:m[k] for k in ['n_samples','input_shape','classes','split','class_counts']},ensure_ascii=False,indent=1))"
fi

# ---------------------------------------------------------------- [2] 训练
echo "### [2/3] 训练模型② ..."
cd "$PROJ/src/train"
"$PY" train_waveform.py --data "$DATA" --out "$RUN" --seed "$SEED" \
    --epochs-float "$EP_FLOAT" --epochs-qat "$EP_QAT" \
    ${LIMIT:+--limit-train "$LIMIT"} $REF_EVAL 2>&1 | tee "$PROJ/logs/train_$(basename $RUN).log"

# ---------------------------------------------------------------- [3] 导出
echo "### [3/3] 导出 quantized_model/ ..."
UMFQ=${UMFQ:-119}
"$PY" export_quantized.py --model "$RUN" --data "$DATA" \
    --out "$DELIV/quantized_model" --per-class 8 --uniform-mfq "$UMFQ" \
    2>&1 | tee "$PROJ/logs/export_$(basename $RUN).log"

echo
echo "=== 交付物 ==="
ls -la "$DELIV/quantized_model"
echo
echo "PIPELINE_DONE"
