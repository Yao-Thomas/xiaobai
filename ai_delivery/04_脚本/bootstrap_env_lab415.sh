#!/usr/bin/env bash
# =============================================================================
# bootstrap_env_lab415.sh —— 任务 A：Lab415 云端 GPU 训练环境（可复现）
#   目标：从零创建独立 conda 环境，不干扰实验室既有的 /data/pengyc_fzu/envs/dl
#   落盘位置全部在 /data（根分区 / 已 100% 满，绝不能往 $HOME 写大文件）
# =============================================================================
set -euo pipefail

PROJ_ROOT=/data/pengyc_fzu/fpga2026_ai
ENV_PREFIX=/data/pengyc_fzu/envs/fpga2026
CONDA=/home/pengyc_fzu/miniconda3/bin/conda
PY_VER=3.10

# ★ 把 cache/tmp 全部重定向到 /data，避免写满根分区
export PIP_CACHE_DIR=$PROJ_ROOT/.cache/pip
export TMPDIR=$PROJ_ROOT/.cache/tmp
export CONDA_PKGS_DIRS=$PROJ_ROOT/.cache/conda_pkgs
export XDG_CACHE_HOME=$PROJ_ROOT/.cache
mkdir -p "$PIP_CACHE_DIR" "$TMPDIR" "$CONDA_PKGS_DIRS" "$PROJ_ROOT/logs"

echo "=== [1/5] 目录 & 磁盘检查 ==="
mkdir -p "$PROJ_ROOT"
df -h /data | tail -n1
echo "根分区剩余（必须 > 1G）:"; df -h / | tail -n1

echo
echo "=== [2/5] 创建 conda 环境 $ENV_PREFIX (python $PY_VER) ==="
if [ -x "$ENV_PREFIX/bin/python" ]; then
  echo "已存在，跳过创建"
else
  "$CONDA" create -y -p "$ENV_PREFIX" "python=$PY_VER" pip -q
fi
PY="$ENV_PREFIX/bin/python"
"$PY" -V

echo
echo "=== [3/5] 安装 PyTorch 2.5.1 + CUDA 11.8 ==="
# 驱动是 470.223.02（CUDA 11.4）；CUDA 11.x 有次版本兼容 ⇒ cu118 wheel 可用
# （绝不能装 cu12x：CUDA 12 需要 >=525 驱动）
#
# ★ 镜像策略（实测结论，很重要）：
#   pypi.org 的【索引】可达，但文件 CDN files.pythonhosted.org **不可达**
#   （Errno 101 Network is unreachable）⇒ 必须换镜像，否则 sympy/jinja2 之类
#   的依赖永远下不下来。实测可达：mirrors.aliyun.com（200）、
#   mirrors.cloud.tencent.com（200）、download.pytorch.org（200）；
#   清华 pypi 镜像返回 403，不可用。
PYPI_MIRROR=${PYPI_MIRROR:-https://mirrors.aliyun.com/pypi/simple/}
PIPCOMMON="--timeout 60 --retries 6"

if "$PY" -c "import torch" 2>/dev/null; then
  echo "torch 已装：$("$PY" -c 'import torch;print(torch.__version__)')"
else
  "$PY" -m pip install -q $PIPCOMMON \
      torch==2.5.1+cu118 torchvision==0.20.1+cu118 torchaudio==2.5.1+cu118 \
      --index-url https://download.pytorch.org/whl/cu118 \
      --extra-index-url "$PYPI_MIRROR"
fi

echo
echo "=== [4/5] 安装其余依赖（走镜像 $PYPI_MIRROR） ==="
"$PY" -m pip install -q $PIPCOMMON --index-url "$PYPI_MIRROR" \
    "numpy==1.26.4" "scipy==1.14.1" "matplotlib==3.9.2" "pandas==2.2.3" \
    "scikit-learn==1.5.2" "tqdm==4.66.5" "pyyaml==6.0.2" "h5py==3.12.1" \
    "fastapi==0.115.6" "uvicorn[standard]==0.34.0" "pydantic==2.10.4" \
    "requests==2.32.3" "python-multipart==0.0.20" \
    "gymnasium==1.0.0" "tensorboard==2.18.0" \
    "transformers==4.46.3" "peft==0.13.2" "datasets==3.1.0" "accelerate==1.1.1" \
    "sentencepiece==0.2.0" "safetensors==0.4.5" "einops==0.8.0" \
    "onnx==1.17.0" "onnxruntime==1.20.1"

echo
echo "=== [5/5] 冻结环境（可复现性验收证据） ==="
"$PY" -m pip freeze > "$PROJ_ROOT/requirements_lock.txt"
wc -l "$PROJ_ROOT/requirements_lock.txt"

echo
echo "=== 验证 ==="
"$PY" - <<'PYEOF'
import torch, numpy, sys
print("python     :", sys.version.split()[0])
print("torch      :", torch.__version__)
print("torch.cuda :", torch.version.cuda)
print("cuda avail :", torch.cuda.is_available())
print("gpu count  :", torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print("   GPU%d %s %.1f GB" % (i, torch.cuda.get_device_name(i),
          torch.cuda.get_device_properties(i).total_memory/1e9))
for m in ["fastapi","uvicorn","gymnasium","peft","transformers","onnxruntime","sklearn"]:
    __import__(m); print("  ok:", m)
PYEOF

echo
echo "BOOTSTRAP_DONE env=$ENV_PREFIX"
