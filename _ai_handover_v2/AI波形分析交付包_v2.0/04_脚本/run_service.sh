#!/usr/bin/env bash
# 启动多模态波形分析服务（Linux / 云端）
#   ./scripts/run_service.sh                 # 0.0.0.0:8000
#   PORT=8765 ./scripts/run_service.sh
#   MODEL=runs/v2_real/model_bundle.pt ./scripts/run_service.sh
set -e
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

PORT="${PORT:-8000}"
MODEL="${MODEL:-runs/v2_full/model_bundle.pt}"
ANOMALY="${ANOMALY:-runs/v2_full/anomaly_stats.npz}"
THREADS="${THREADS:-4}"

if [ ! -f "$MODEL" ]; then
  echo "找不到模型：$MODEL" >&2
  exit 1
fi

ARGS=(-m wave_ai.serve --host 0.0.0.0 --port "$PORT" --model "$MODEL" --threads "$THREADS")
if [ -f "$ANOMALY" ]; then ARGS+=(--anomaly "$ANOMALY"); fi
exec python "${ARGS[@]}"
