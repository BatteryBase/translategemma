#!/usr/bin/env bash
# 准备 27B-Q8 GGUF 多卡环境：检查 CUDA llama-cpp → 下载权重 → 冒烟测试
set -euo pipefail
cd "$(dirname "$0")/.."
source ~/miniconda3/etc/profile.d/conda.sh
conda activate translategemma

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"

CACHE_DIR="${HOME}/.cache/translate/models"
RAW="${CACHE_DIR}/translategemma-27b-it.Q8_0.gguf"
DEST="${CACHE_DIR}/translategemma-27b-it-Q8.gguf"
URL="${HF_ENDPOINT}/mradermacher/translategemma-27b-it-GGUF/resolve/main/translategemma-27b-it.Q8_0.gguf"
# Q8 完整文件约 28–30GB
MIN_BYTES=20000000000

echo "=== 1) CUDA llama-cpp ==="
python - <<'PY'
from llama_cpp.llama_cpp import llama_supports_gpu_offload
assert llama_supports_gpu_offload(), "llama-cpp 无 CUDA，请见 docs/SERVER_SETUP_27B_Q8.md"
print("gpu_offload OK")
PY

mkdir -p "${CACHE_DIR}"

echo "=== 2) 下载 GGUF Q8（可断点续传）==="
if [[ -f "${DEST}" ]] && [[ "$(stat -c%s "${DEST}")" -gt "${MIN_BYTES}" ]]; then
  echo "already have ${DEST} ($(stat -c%s "${DEST}") bytes)"
elif [[ -f "${RAW}" ]] && [[ "$(stat -c%s "${RAW}")" -gt "${MIN_BYTES}" ]]; then
  ln -sf "${RAW}" "${DEST}" 2>/dev/null || cp -f "${RAW}" "${DEST}"
  echo "linked/copied ${RAW} -> ${DEST}"
else
  echo "wget -c ${URL}"
  wget -c --timeout=120 --tries=0 --retry-connrefused -O "${RAW}" "${URL}"
  # 规范名供 get_model_path 使用
  if [[ "$(stat -c%s "${RAW}")" -gt "${MIN_BYTES}" ]]; then
    ln -sf "$(basename "${RAW}")" "${DEST}" 2>/dev/null || cp -f "${RAW}" "${DEST}"
  fi
fi

SIZE="$(stat -c%s "${DEST}" 2>/dev/null || echo 0)"
if [[ "${SIZE}" -lt "${MIN_BYTES}" ]]; then
  echo "ERROR: download incomplete (${SIZE} bytes). Re-run this script to resume."
  exit 1
fi
echo "model OK: ${DEST} (${SIZE} bytes)"

echo "=== 3) 四卡加载冒烟测试 ==="
python - <<'PY'
from llama_cpp import Llama
from translategemma_cli.config import get_model_path
p = get_model_path("27b", 8, "gguf")
print("loading", p)
m = Llama(model_path=str(p), n_gpu_layers=-1, tensor_split=[1, 1, 1, 1], n_ctx=2048, verbose=False)
out = m("Translate to English:\n你好\n", max_tokens=16)
text = out["choices"][0]["text"] if isinstance(out, dict) else str(out)
print("sample:", repr(text[:200]))
print("LOAD_OK")
PY

echo "=== 完成。启动: cd scripts && ./start_api.sh ==="
