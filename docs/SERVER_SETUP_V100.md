# V100 多卡部署说明（27B PyTorch）

> **当前推荐**：27B-Q8 GGUF，见 `docs/SERVER_SETUP_27B_Q8.md`。  
> 假死/超时原因汇总：`docs/TROUBLESHOOTING_HANGS.md`。  
> 下文保留全精度 PyTorch 路径说明（易 CPU offload，长段不稳定）。

## 适用环境

- 4× Tesla V100-SXM2-16GB
- PyTorch `2.5.1+cu124`（V100 不支持 PyTorch 2.12+cu130）
- 模型：ModelScope 下载的 `translategemma-27b-it`（~52GB）

## 快速启动

```bash
conda activate translategemma
cd ~/nhwork/translategemma
cp .env.example .env   # 首次
# 编辑 .env：MODEL_LOCAL_PATH、NVIDIA_VISIBLE_DEVICES 等
bash scripts/start_api.sh
```

## 本次服务端改动

1. **`.env` 自动加载**：`app_fastapi.py` 启动时读取同目录 `.env`
2. **本地模型识别**：`model.py` 支持 `MODEL_LOCAL_PATH`、ModelScope 缓存，无需连 HuggingFace
3. **PyTorch 全精度**：`bfloat16` + `device_map=auto` 四卡分片
4. **启动预加载**：`MODEL_PRELOAD=true` 避免首次请求超时
5. **端口 80**：`scripts/start_api.sh` 用 `sudo python -m uvicorn` 正确绑定特权端口

## 配置示例（`.env`）

```bash
PORT=80
MODEL_NAME=27b
BACKEND=pytorch
MODEL_LOCAL_PATH=/home/user/nhwork/translategemma/models/translategemma-27b-it
NVIDIA_VISIBLE_DEVICES=0,1,2,3
MODEL_PRELOAD=true
GPU_IDLE_TIMEOUT=3600
```

## 下载模型（推荐 GGUF Q8）

全精度 PyTorch 路径已弃用。请用：

```bash
python scripts/download_27b_q8.py
```

详见 `docs/SERVER_SETUP_27B_Q8.md`。

## SSH 隧道（外网 80 不通时）

在本地 Mac 执行：

```bash
bash scripts/ssh_tunnel_api.sh
# 然后访问 http://127.0.0.1:8080/health
```
