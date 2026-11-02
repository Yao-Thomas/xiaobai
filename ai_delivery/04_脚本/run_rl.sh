#!/usr/bin/env bash
# =============================================================================
# run_rl.sh —— 任务 E：RL 训练一键脚本（在 lab415 上跑）
#   [1] 训练示波器自动设置策略 + 自动验收（五输入成功率/回报）
#   [2] 训练音频 EQ 调优策略 + 平坦度报告
#   [3] 量化导出 + 强制自检（reference_in/out.bin + weights.bin + model_spec.json）
#
# 用法：
#   bash scripts/run_rl.sh                  # 默认规模（GPU）
#   SMOKE=1 bash scripts/run_rl.sh          # 冒烟（小规模，快速跑通）
# =============================================================================
set -euo pipefail

PROJ=${PROJ:-/data/pengyc_fzu/fpga2026_ai}
PY=${PY:-/data/pengyc_fzu/envs/fpga2026/bin/python}
RUNS=${RUNS:-$PROJ/runs}
DELIV=${DELIV:-$PROJ/deliverables}
SEED=${SEED:-20261001}

mkdir -p "$RUNS" "$DELIV" "$PROJ/logs"

if [ "${SMOKE:-0}" = "1" ]; then
  SCOPE_STEPS=4096; EQ_STEPS=4096; N_ACCEPT=10; N_ROOMS=4
  SCOPE_RUN=$RUNS/scope_smoke; EQ_RUN=$RUNS/eq_smoke
  echo "### SMOKE 模式 ###"
else
  SCOPE_STEPS=300000; EQ_STEPS=200000; N_ACCEPT=50; N_ROOMS=20
  SCOPE_RUN=$RUNS/scope_policy_v1; EQ_RUN=$RUNS/eq_policy_v1
fi

echo "=============================================================="
echo " PROJ=$PROJ"
echo " PY=$PY"
echo " SEED=$SEED"
echo " SCOPE_RUN=$SCOPE_RUN"
echo " EQ_RUN=$EQ_RUN"
echo "=============================================================="
"$PY" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.device_count())"

cd "$PROJ/src/rl"

# ---------------------------------------------------------------- [1] 示波器
echo "### [1/3] 训练示波器自动设置策略 ..."
"$PY" train_scope.py --seed "$SEED" --total-steps "$SCOPE_STEPS" \
    --out "$SCOPE_RUN" --n-accept "$N_ACCEPT" \
    2>&1 | tee "$PROJ/logs/rl_scope.log"

# ---------------------------------------------------------------- [2] 音频 EQ
echo "### [2/3] 训练音频 EQ 调优策略 ..."
"$PY" train_eq.py --seed "$SEED" --total-steps "$EQ_STEPS" \
    --out "$EQ_RUN" --n-rooms "$N_ROOMS" \
    2>&1 | tee "$PROJ/logs/rl_eq.log"

# ---------------------------------------------------------------- [3] 量化导出
echo "### [3/3] 量化导出 + 强制自检 ..."
"$PY" quantize_policy.py --model "$SCOPE_RUN" --out "$DELIV/scope_policy_quantized" \
    2>&1 | tee "$PROJ/logs/rl_quant_scope.log"
"$PY" quantize_policy.py --model "$EQ_RUN" --out "$DELIV/eq_policy_quantized" \
    2>&1 | tee "$PROJ/logs/rl_quant_eq.log"

echo
echo "=== 交付物 ==="
ls -la "$DELIV/scope_policy_quantized"
ls -la "$DELIV/eq_policy_quantized"
echo
echo "RL_PIPELINE_DONE"
