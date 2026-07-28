# 相对原版 TranslateGemma 的改动说明

本文说明当前仓库（`BatteryBase/translategemma`，V100 部署分支）相对上游原版（`neosun100/translategemma` / `origin/main`）多了什么、改了什么。

- **对比基准**：`origin/main`（上游公开版，约 `02d11a2`）
- **当前主线**：27B-Q8 GGUF 多卡 + 术语表可用（标签 `v100-27b-q8-glossary`）
- **历史标签**：
  - `v100-27b-bf16-full`：曾用过的 27B 全精度 PyTorch 快照
  - `v100-27b-q8-gguf`：切到 GGUF 多卡
  - `v100-27b-q8-glossary`：术语表 finalize 修复后可稳定批处理

假死/超时细节见 [`TROUBLESHOOTING_HANGS.md`](./TROUBLESHOOTING_HANGS.md)。  
GGUF 部署见 [`SERVER_SETUP_27B_Q8.md`](./SERVER_SETUP_27B_Q8.md)。

---

## 一、改动概览（相对原版多出来的能力）

| 能力 | 原版 | 本仓库 |
|------|------|--------|
| 默认推理 | 通用 GGUF/多后端 | **面向 4×V100 的 27B-Q8 GGUF + `tensor_split` 多卡** |
| 模型获取 | 多为 HuggingFace | **ModelScope 下载脚本**（国内网络） |
| 领域术语 | 无 / 弱 | **电池领域 glossary.csv + 掩码/还原** |
| 批量写库 | 无 | **ArangoDB `nyztest.my_nyz_article` 中译英批处理**（断点续跑） |
| API 稳定性 | 同步推理易堵 | **单线程 CUDA 池、health 不跨线程碰 GPU、可选超时** |
| 运维文档 | 通用 README | **V100 / Q8 / 假死排查** 专项文档 |

---

## 二、按文件：改了什么、干什么用

### 1. 核心推理与配置

#### `translategemma_cli/model.py`
- **多卡 GGUF**：`_load_gguf` 支持 `tensor_split`，环境变量 `GGUF_TENSOR_SPLIT` / `GGUF_N_GPU_LAYERS` / `GGUF_N_CTX`。
- **本地权重**：识别 ModelScope / `MODEL_LOCAL_PATH` 等本地 HF 目录（全精度路径遗留）。
- **CUDA 检查**：要求 `llama_supports_gpu_offload()`，避免误用无 GPU 的 llama-cpp。

#### `translategemma_cli/config.py`
- 增加 GGUF 多卡相关配置项与环境变量读取（`gguf_tensor_split` 等）。

#### `translategemma_cli/translator.py`
- GGUF 生成增加 `stop=["<end_of_turn>", "<eos>"]`，减少无意义长生成。
- 与术语表联动的翻译路径（掩码文本进模型、再 finalize）。

#### `translategemma_cli/glossary.py`（**新增**）
- 从 `docs/glossary.csv` 加载中英术语。
- 译前最长匹配掩码为 `⟦Gn⟧`，译后还原为目标英文。
- **修复** `finalize_output` 在「期望命中次数 > 实际出现次数」时对单词语目标（如 Charge）的 **死循环**（批处理第 6 段反复超时的主因）。

#### `translategemma_cli/chunker.py`
- 分块时配合术语表，避免切开占位符（`split_text_preserving_placeholders` 相关能力）。

#### `docs/glossary.csv`（**新增**）
- 电池/制造领域中英术语表（约 280+ 条），供 glossary 使用。

#### `tests/test_glossary.py`（**新增/扩充**）
- 掩码、还原、以及「欠产出目标词不挂死」的回归测试。

---

### 2. API 服务（FastAPI）

#### `app_fastapi.py`
相对原版主要增强：

| 点 | 说明 |
|----|------|
| `.env` 加载 | 启动时读项目根目录 `.env`；`NVIDIA_VISIBLE_DEVICES` → `CUDA_VISIBLE_DEVICES` |
| 默认模型 | 默认偏向 `27b` / Q8 / `gguf` |
| 术语表开关 | `DEFAULT_USE_GLOSSARY`、请求体 `use_glossary` |
| 分块参数 | `MAX_CHUNK_LENGTH` / `DEFAULT_OVERLAP` / `REPETITION_PENALTY` |
| **单线程推理池** | `_TRANSLATE_EXECUTOR(max_workers=1)`：预加载与翻译**同一线程**，避免 llama.cpp/CUDA 跨线程假死 |
| Health | GGUF 模式下不在事件循环线程调 `torch.cuda.mem_get_info()` |
| 超时 | `TRANSLATE_TIMEOUT`：`0` = 不限制（批处理长文）；`>0` 则 `asyncio.wait_for` |
| 预加载 | `MODEL_PRELOAD=true` 时启动即加载模型 |

#### `.env.example`
- 文档化 V100 四卡、27B-Q8 GGUF、`GGUF_TENSOR_SPLIT`、术语表、`TRANSLATE_TIMEOUT=0` 等推荐配置。

---

### 3. 启动与下载脚本（**多为新增**）

| 文件 | 作用 |
|------|------|
| `scripts/start_api.sh` | 激活 conda、加载 `.env`、启动 uvicorn（非特权端口无需 sudo） |
| `scripts/download_27b_q8.py` | 从 ModelScope 下 27B Q8 GGUF，链到 `~/.cache/translate/models/translategemma-27b-it-Q8.gguf` |
| `scripts/setup_27b_q8_multigpu.sh` | 检查 CUDA llama-cpp + 下载 + 多卡冒烟（可选） |
| `scripts/ssh_tunnel_api.sh` | 本机 SSH 隧道访问远程 API |
| `start.sh` | Docker/一键启动相关环境变量补充（含 GGUF 默认等） |

> 已删除旧的 `scripts/download_modelscope.py`（全精度 PyTorch 下载）；全精度路径仅作历史/文档保留。

---

### 4. 批处理写回 ArangoDB（**新增，业务侧**）

| 文件 | 作用 |
|------|------|
| `scripts/batch_article_zj_to_english.py` | 主脚本：从 `nyztest.my_nyz_article` 取待译文章 → 调本机 `8022` 翻译 → 写回英文字段 |
| `scripts/batchArticleZJToEnglish.js` | 早期 JS 版（逻辑对应关系保留） |

**写回字段（同一文档 UPDATE）**：

- `content_english`：content 树深拷贝后 text 节点换英文  
- `title_english` / `summary_english` / `text_english` / `index_english`  
- `wordNumber_english`、`updateTime`  
- `hasZhangJun=1`：本脚本完成标记（下次 `FILTER hasZhangJun != 1` 会跳过）

**断点**：`scripts/.zj_progress/<文章key>.json`，段级续跑。  
**失败汇总**：跑完打印失败文章标题 + 原因。  
**超时**：默认 HTTP/API 均不限制（`TRANSLATE_TIMEOUT=0`），尽量把每篇跑完。

---

### 5. 文档（**新增**）

| 文件 | 内容 |
|------|------|
| `docs/SERVER_SETUP_V100.md` | V100 全精度/环境说明（现推荐改走 Q8） |
| `docs/SERVER_SETUP_27B_Q8.md` | 27B-Q8 GGUF 多卡部署 |
| `docs/TROUBLESHOOTING_HANGS.md` | 假死原因全集（驱动、跨线程、术语表死循环、端口占用等） |
| `docs/CHANGES_FROM_UPSTREAM.md` | 本文：相对原版的改动总览 |

---

### 6. 其它小改

| 文件 | 说明 |
|------|------|
| `.gitignore` | 忽略本地 `.env`、进度目录等敏感/临时文件 |

---

## 三、相对原版：建议保留的「本仓库特色」提交链

```
ac33333  ModelScope / V100 / start_api（全精度落地）
f14e4cb  术语表 + Arango 批处理 + API 增强（bf16 快照标签）
b60d535  切换 27B-Q8 GGUF 多卡
83bb23c  术语表 finalize 修复 + 假死文档（glossary 可用标签）
(+ 工作区) TRANSLATE_TIMEOUT=0 + 失败文章汇总
```

上游 `origin/main` 仍是通用 Web UI / REST / MCP 产品形态；本仓库在其上叠加了 **V100 生产批处理 + 领域术语 + GGUF 多卡运维**。

---

## 四、文件清单（相对 `origin/main...HEAD` 的 diff 范围）

```
.env.example
.gitignore
app_fastapi.py
docs/SERVER_SETUP_27B_Q8.md          (新增)
docs/SERVER_SETUP_V100.md            (新增)
docs/TROUBLESHOOTING_HANGS.md        (新增)
docs/glossary.csv                    (新增)
scripts/batchArticleZJToEnglish.js   (新增)
scripts/batch_article_zj_to_english.py (新增)
scripts/download_27b_q8.py           (新增)
scripts/setup_27b_q8_multigpu.sh     (新增)
scripts/ssh_tunnel_api.sh            (新增)
scripts/start_api.sh                 (新增)
start.sh
tests/test_glossary.py               (新增)
translategemma_cli/chunker.py
translategemma_cli/config.py
translategemma_cli/glossary.py       (新增)
translategemma_cli/model.py
translategemma_cli/translator.py
```

统计约：**20 个路径，+2500 / −170 行量级**（随后续提交略有浮动）。

---

## 五、运行时「原版没有」的推荐配置（摘要）

```bash
BACKEND=gguf
MODEL_NAME=27b
QUANTIZATION=8
GGUF_N_GPU_LAYERS=-1
GGUF_TENSOR_SPLIT=1,1,1,1
GGUF_N_CTX=4096
MODEL_PRELOAD=true
DEFAULT_USE_GLOSSARY=true
TRANSLATE_TIMEOUT=0          # 批处理不限时
PORT=8022
NVIDIA_VISIBLE_DEVICES=0,1,2,3
```

启动：`cd scripts && ./start_api.sh`  
批处理：`python batch_article_zj_to_english.py --limit N`
