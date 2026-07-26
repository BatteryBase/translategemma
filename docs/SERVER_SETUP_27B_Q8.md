# 27B-Q8 GGUF 多卡（4×V100）部署

## 配置要点

| 项 | 值 |
|----|----|
| 后端 | `BACKEND=gguf` |
| 模型 | `MODEL_NAME=27b` + `QUANTIZATION=8` |
| 显存 | ~28–35GB 总计，`GGUF_TENSOR_SPLIT=1,1,1,1` 均分 4 卡 |
| 端口 | `8022` |

依赖：**带 CUDA 的 llama-cpp-python**（`llama_supports_gpu_offload()==True`）。

## 一键准备

```bash
conda activate translategemma
cd ~/nhwork/translategemma
bash scripts/setup_27b_q8_multigpu.sh
```

脚本会：检查 CUDA llama-cpp → 下载 `translategemma-27b-it.Q8_0.gguf` → 四卡加载冒烟测试。

## 启动

```bash
cd ~/nhwork/translategemma/scripts
./start_api.sh
# 另开终端
curl -m 10 http://127.0.0.1:8022/health
```

## 重建 CUDA llama-cpp（若 GPU offload 为 False）

```bash
export CUDA_HOME=/usr/local/cuda-12.4
export PATH="$CUDA_HOME/bin:$PATH"
export CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=70"
export FORCE_CMAKE=1
pip install --force-reinstall --no-cache-dir --no-binary=llama-cpp-python 'llama-cpp-python==0.3.32'
```

V100 为 compute capability 70。

## 与全精度对比

| | 27B bf16 全精度 | **27B-Q8 GGUF** |
|--|----------------|-----------------|
| 显存 | ~54GB+，易 CPU offload | ~28–35GB，四卡轻松 |
| 稳定性 | 长段易卡死 | 适合批处理（需注意术语表/驱动，见下） |
| 质量 | 最高 | 接近，实务够用 |

## 假死 / 超时

若出现短句正常、长段 180s 超时、CPU 空转、或 `address already in use`，见：

**[TROUBLESHOOTING_HANGS.md](./TROUBLESHOOTING_HANGS.md)**

（含驱动 mismatch、跨线程 CUDA、术语表 finalize 死循环、端口占用等完整原因与修复。）
