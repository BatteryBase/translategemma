#!/usr/bin/env bash
# 启动 TranslateGemma API（支持 PORT=80，自动处理 sudo + conda 环境）
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh
conda activate translategemma

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -n "${NVIDIA_VISIBLE_DEVICES:-}" && -z "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  export CUDA_VISIBLE_DEVICES="${NVIDIA_VISIBLE_DEVICES}"
fi

PORT="${PORT:-80}"
PYTHON="$(which python)"
UVICORN_ARGS=(app_fastapi:app --host 0.0.0.0 --port "${PORT}")

echo "启动 TranslateGemma API，端口 ${PORT}"

if [[ "${PORT}" -lt 1024 ]]; then
  # 80 等特权端口需 root；必须用 python -m uvicorn 保留 conda 环境
  # 错误示例: sudo uvicorn ...  → ModuleNotFoundError: click
  exec sudo -E env "PATH=${PATH}" "${PYTHON}" -m uvicorn "${UVICORN_ARGS[@]}"
else
  exec "${PYTHON}" -m uvicorn "${UVICORN_ARGS[@]}"
fi
