#!/usr/bin/env bash
# =============================================================================
# run_agent.sh —— 任务 D 一键端到端（在 lab415 上跑）
#   [1] 建语料（RAG 知识库 + LoRA 指令数据集，纯标准库）
#   [2] RAG 基线评测（纯标准库）
#   [3] LoRA 微调（Qwen2.5-0.5B-Instruct，peft）
#   [4] 量化 + 显存实测 + feasibility.md
#   [5] 三条路线诚实对比（RAG / LoRA / RAG+LoRA）
#
# 用法：
#   bash scripts/run_agent.sh                 # 完整流程（需 4×2080Ti）
#   SMOKE=1 bash scripts/run_agent.sh         # 冒烟：1 epoch + --dummy 量化，不下载大权重
#   FORCE_CORPUS=1 DOCROOT=<文档根> bash scripts/run_agent.sh   # 重建语料
# =============================================================================
set -euo pipefail

PROJ=${PROJ:-/data/pengyc_fzu/fpga2026_ai}
PY=${PY:-/data/pengyc_fzu/envs/fpga2026/bin/python}
AGENT=$PROJ/src/agent
SEED=${SEED:-20261001}

mkdir -p "$PROJ/logs" "$AGENT/lora_model"

if [ "${SMOKE:-0}" = "1" ]; then
  EPOCHS=1; BATCH=2; GRAD=2; QUANT="--dummy"
  echo "### SMOKE 模式（1 epoch + --dummy 量化）###"
else
  EPOCHS=3; BATCH=4; GRAD=8; QUANT="--model $AGENT/lora_model/merged"
fi

echo "=============================================================="
echo " PROJ=$PROJ"
echo " PY=$PY"
echo " AGENT=$AGENT"
echo "=============================================================="
"$PY" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.device_count())" 2>/dev/null || echo "torch 未检测到（前两步纯标准库仍可跑）"

# ---------------------------------------------------------------- [1] 建语料
echo "### [1/5] 建语料（RAG 知识库 + LoRA 数据集）..."
cd "$AGENT"
if [ ! -f "$AGENT/kb/chunks.jsonl" ] || [ "${FORCE_CORPUS:-0}" = "1" ]; then
  "$PY" build_corpus.py ${DOCROOT:+--project-root "$DOCROOT"} 2>&1 | tee "$PROJ/logs/agent_corpus.log"
else
  echo "kb/chunks.jsonl 已存在，跳过建语料（FORCE_CORPUS=1 可强制重建）"
fi

# ---------------------------------------------------------------- [2] RAG 基线
echo "### [2/5] RAG 基线评测（纯标准库）..."
"$PY" eval.py --kb "$AGENT/kb/chunks.jsonl" \
    --out "$AGENT/eval_report.json" --out-md "$AGENT/eval_report.md" \
    2>&1 | tee "$PROJ/logs/agent_eval.log"

# ---------------------------------------------------------------- [3] LoRA 训练
echo "### [3/5] LoRA 微调 ..."
"$PY" train_lora.py --data "$AGENT/lora_data" --out "$AGENT/lora_model" \
    --epochs "$EPOCHS" --batch "$BATCH" --grad-accum "$GRAD" --seed "$SEED" \
    2>&1 | tee "$PROJ/logs/agent_train_lora.log"

# ---------------------------------------------------------------- [4] 量化
echo "### [4/5] 量化 + 显存实测 ..."
# shellcheck disable=SC2086
"$PY" quantize_llm.py $QUANT --out "$AGENT/lora_model/quant" \
    2>&1 | tee "$PROJ/logs/agent_quantize.log"

# ---------------------------------------------------------------- [5] 对比
echo "### [5/5] 三条路线诚实对比 ..."
if [ "${SMOKE:-0}" = "1" ]; then
  echo "SMOKE 模式跳过 LoRA 对比（无合并模型），只评 RAG"
  "$PY" compare_rag_vs_lora.py --kb "$AGENT/kb/chunks.jsonl" --out "$AGENT/compare_report"
else
  "$PY" compare_rag_vs_lora.py --kb "$AGENT/kb/chunks.jsonl" \
      --lora-model "$AGENT/lora_model/merged" --out "$AGENT/compare_report" \
      2>&1 | tee "$PROJ/logs/agent_compare.log"
fi

echo
echo "=== 交付物 ==="
ls -la "$AGENT/kb" "$AGENT/lora_data" "$AGENT/lora_model" 2>/dev/null || true
echo
echo "RUN_AGENT_DONE"
