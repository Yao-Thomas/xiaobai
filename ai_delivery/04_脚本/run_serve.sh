#!/usr/bin/env bash
# =============================================================================
# run_serve.sh —— 在 lab415 上启动「系统管家小白」云端推理服务（任务 G + 任务 H）
#
# 用法：
#   bash scripts/run_serve.sh                          # 默认 0.0.0.0:8000
#   SERVE_PORT=8001 bash scripts/run_serve.sh          # 换端口
#   SERVE_API_KEY=your-key bash scripts/run_serve.sh   # 开启 api_key 鉴权
#
# 说明：
#   · 依赖 conda 环境 /data/pengyc_fzu/envs/fpga2026（fastapi/uvicorn/pydantic）
#   · 模型目录/同步库路径由 src/serve/config.py 从自身位置解析，
#     与 cwd 无关（deliverables/quantized_model 、data/sync.db）
#   · 阻塞推理已放进线程池，不阻塞事件循环
# =============================================================================
set -euo pipefail

PROJ=${PROJ:-/data/pengyc_fzu/fpga2026_ai}
PY=${PY:-/data/pengyc_fzu/envs/fpga2026/bin/python}
HOST=${SERVE_HOST:-0.0.0.0}
PORT=${SERVE_PORT:-8000}

if [ ! -x "$PY" ]; then
  echo "找不到 python：$PY（请先跑 scripts/bootstrap_env_lab415.sh）" >&2
  exit 1
fi

cd "$PROJ/src/serve"

echo "=============================================================="
echo " 系统管家小白 · 云端推理服务"
echo "   PROJ=$PROJ"
echo "   HOST=$HOST  PORT=$PORT"
echo "   API_KEY 已配置: $([ -n "${SERVE_API_KEY:-}" ] && echo yes || echo no)"
echo "=============================================================="

exec "$PY" -m uvicorn api:app --host "$HOST" --port "$PORT"
