# TranslateGemma 假死 / 超时排查与修复总结（V100 · 27B-Q8 GGUF）

本文记录在 4×V100 上跑 **27B-Q8 GGUF** + 批处理时，多次出现「短句正常、长段/第 N 条卡住、`/health` 看似还活、180s 超时」的原因与已落地的解决方案。

相关配置见：`docs/SERVER_SETUP_27B_Q8.md`、`.env.example`。

---

## 现象速查

| 表象 | 常见根因（见下文编号） |
|------|------------------------|
| 短句 1–3s 成功，某一段（如 `len=166`）卡满 1800s / 180s | ④ 术语表 finalize 死循环；或 ① 驱动假死 |
| `/health` 仍 200，但翻译永远不回 | ② 跨线程 CUDA；③ 单线程队列被堵；④ finalize 空转 |
| API 进程某个线程 **CPU ~100%**，`nvidia-smi` GPU-Util **0%** | 多为 ④（CPU 死循环）或 ①（CUDA 假死后 CPU 空等） |
| `nvidia-smi`：`Driver/library version mismatch` | ① |
| 启动报 `address already in use` + `Failed to load model ... Q8.gguf` | ⑤ 旧进程占端口/占文件 |
| `Connection refused` 到 8022 | 服务没起来（重启/被 kill 后未再 `./start_api.sh`） |
| 日志出现 `Loading checkpoint shards`（PyTorch）却配置了 GGUF | ⑥ 仍在跑旧全精度进程或 `BACKEND` 未生效 |

---

## 原因 ①：NVIDIA 驱动用户态与内核模块版本不一致

### 为什么会假死

升级/安装了新的 NVIDIA 用户态库后**没有 reboot**，内核里还是旧模块，例如：

- 内核模块：`580.159.xx`
- 用户态 `libnvidia-ml`：`580.173.xx`

此时 `nvidia-smi` 报 mismatch；CUDA 仍可能「看得到 4 张卡」，但推理时偶发**内核调用不返回**。表现：翻译线程长时间占 CPU，GPU 利用率 0。

### 解决方案

1. **有带外控制台（IPMI/云网页终端）时**：`sudo reboot`，起来后确认：

   ```bash
   nvidia-smi   # Driver Version 与库一致，能列出 4×V100
   ```

2. 本机 SSH 为 **`22333` 端口**（不是 22）：

   ```bash
   ssh -p 22333 user@<公网IP>
   ```

3. 仅有 SSH、曾 reboot 后登不上时：先不要盲 reboot；假死可先重启 API（见文末「日常操作」）。

4. reboot **不会**清掉 GGUF 权重，**不必**重装 conda / llama-cpp；只需再执行 `./start_api.sh`。

---

## 原因 ②：llama.cpp / CUDA 跨线程使用同一模型实例

### 为什么会假死

曾把：

- **预加载**放在默认 `ThreadPoolExecutor`（`run_in_executor(None, ...)`）
- **翻译**放在另一个池 `_TRANSLATE_EXECUTOR`

llama.cpp 的 CUDA 上下文**不是线程安全的**。模型在线程 A 加载，在线程 B 推理 → 间歇性假死。

另外：`/health` 在事件循环线程里调 `torch.cuda.mem_get_info()`，与 GGUF 推理线程同时碰 CUDA，也会打架。

### 解决方案（已改 `app_fastapi.py`）

1. 预加载、翻译、切模型**全部**走同一个 `_TRANSLATE_EXECUTOR`（`max_workers=1`）。
2. `BACKEND=gguf` 时，`/health` **不再**在异步线程里查 `torch.cuda` 显存，只返回 GGUF 状态摘要。

---

## 原因 ③：单线程推理队列 + 一次假死后全堵死

### 为什么感觉「一直很慢」

推理线程池只有 **1** 个 worker（避免多请求并发抢同一份 GGUF）。  
任意一条请求假死（①/②/④）后：

- 该 worker 一直不释放  
- 后续所有 `/api/translate` 在队列里排队  
- `/health` 仍可能 200（事件循环没堵时）  
- 批处理 Ctrl+C 只断客户端，**服务端仍在空转**

所以会感觉「怎么重启批处理还是挂」——其实是**旧推理没死干净**。

### 解决方案

1. 超时保护：`TRANSLATE_TIMEOUT`（默认 180s），超时立即返回错误，避免干等半小时。  
   > 注意：超时后**卡住的那条线程仍可能占着 executor**，需重启 API 才能彻底清掉。
2. 假死后标准动作：杀旧进程再启（见文末）。
3. GGUF 生成增加 `stop=["<end_of_turn>", "<eos>"]`，减少无意义长生成。

---

## 原因 ④：术语表 `finalize_output` 死循环（第 6 段反复超时的主因）

### 为什么会假死

术语表流程：

1. 原文命中词（如「锂离子电池」「充电」「放电」）→ 换成 `⟦G0⟧`…  
2. **模型推理往往几秒就完成**（GPU 正常）  
3. `finalize_output` 把占位符还原成英文术语，并尝试「纠错」错误译法  

旧逻辑第 4 步：若原文「充电」出现 **2** 次，期望译文里有 **2** 个 `Charge`；模型只产出 **1** 个时，代码用 **IGNORECASE** 正则匹配 `Charge`，匹配到的已经是正确词，`sub` 等于没改，`actual` 永远 `< expected` → **`while` 死循环**。

特征：

- CPU ~100%，GPU-Util 0%  
- 关掉 `use_glossary` 后同一段立刻成功（约数秒）  
- 独立 `llama.cpp` 直调带 `⟦G⟧` 的 prompt 也正常 → **不是 GGUF 不会翻占位符，是后处理死循环**

### 解决方案（已改 `translategemma_cli/glossary.py`）

1. 替换循环增加**进度守卫**：`sub` 后字符串不变或 `count` 不增加则立即 `break`。  
2. **禁止**对单词语目标（`Charge` / `Anode` 等）跑「按 target 自身 IGNORECASE 再替换」的逻辑。  
3. 仅对**多词**目标做空格归一（如 `Li-ion  Battery` → `Li-ion Battery`）。  
4. 回归用例：`tests/test_glossary.py` 中  
   `test_finalize_underproduced_targets_does_not_hang`。  
5. 术语表可继续开启：`.env` 里 `DEFAULT_USE_GLOSSARY=true`；批处理传 `use_glossary: true`。

---

## 原因 ⑤：重复启动 API，端口 / 模型文件被占用

### 为什么失败

旧 uvicorn 仍占 `8022`，且 mmap 着 `translategemma-27b-it-Q8_0.gguf`。再跑 `./start_api.sh` 会出现：

- `Failed to load model from file: ...-Q8.gguf`  
- `[Errno 98] address already in use`

### 解决方案

先停干净再启（只启**一次**）：

```bash
# 按端口杀
kill $(ss -tlnp | awk '/:8022/ {if (match($0,/pid=[0-9]+/)) print substr($0,RSTART+4,RLENGTH-4)}')

# 或
pkill -f 'python -m uvicorn'

cd ~/nhwork/translategemma/scripts && ./start_api.sh
curl -s http://127.0.0.1:8022/health
```

不要在多个终端同时 `./start_api.sh`。

---

## 原因 ⑥：以为已是 GGUF，实际还在跑旧 PyTorch 全精度

### 为什么会假死

全精度 27B + `device_map=auto` 在 4×16GB 上会 **CPU offload**，日志有：

- `Loading checkpoint shards`  
- `parameters ... offloaded to the cpu`  

长段极慢或卡死；短句偶尔还能过。标签/提交：全精度快照 `v100-27b-bf16-full`；当前 GGUF 快照 `v100-27b-q8-gguf`。

### 解决方案

`.env` 必须为：

```bash
BACKEND=gguf
MODEL_NAME=27b
QUANTIZATION=8
GGUF_N_GPU_LAYERS=-1
GGUF_TENSOR_SPLIT=1,1,1,1
```

启动日志应出现：`GGUF multi-GPU` / `GGUF model loaded`，**不应**再出现 `Loading checkpoint shards`。  
权重路径：`~/.cache/translate/models/translategemma-27b-it-Q8.gguf`（链到 `*_Q8_0.gguf`）。

---

## 原因 ⑦（次要）：同步推理曾堵死事件循环

早期在 async 路由里直接调同步 `translate()`，一条长请求占满唯一 worker 时，连 `/health` 都不回。

### 解决方案

翻译放到 `_TRANSLATE_EXECUTOR`，健康检查与推理解耦（在 ② 的约束下仍保证同池碰模型）。

---

## 已落地改动清单

| 位置 | 改动 |
|------|------|
| `app_fastapi.py` | 单线程池；预加载/翻译同池；GGUF 下 health 不碰 torch.cuda；`TRANSLATE_TIMEOUT` |
| `translategemma_cli/translator.py` | GGUF `stop=["<end_of_turn>", "<eos>"]` |
| `translategemma_cli/glossary.py` | 修复 finalize 死循环 |
| `translategemma_cli/model.py` / `config.py` | `tensor_split`、多卡 GGUF 加载 |
| `.env` / `.env.example` | 27B-Q8 GGUF + 超时等 |
| `scripts/download_27b_q8.py` | ModelScope 下载 Q8 |
| `scripts/batch_article_zj_to_english.py` | 批处理走本机 API，可开术语表 |

Git 标签：`v100-27b-q8-gguf`（fork：`BatteryBase/translategemma`）。

---

## 日常操作（假死应急）

```bash
# 1) 看是否假死：某线程 CPU 很高，GPU-Util 接近 0
ps -L -o tid,pcpu,stat -p $(pgrep -f 'python -m uvicorn') | sort -k2 -nr | head
nvidia-smi

# 2) 重启 API
kill $(ss -tlnp | awk '/:8022/ {if (match($0,/pid=[0-9]+/)) print substr($0,RSTART+4,RLENGTH-4)}')
cd ~/nhwork/translategemma/scripts && ./start_api.sh

# 3) 冒烟（含术语表）
curl -s http://127.0.0.1:8022/health
# 再跑批处理；checkpoint 在 scripts/.zj_progress/ ，可续传
python batch_article_zj_to_english.py --limit 1
```

若 `nvidia-smi` 再次 mismatch，在有控制台的前提下 reboot 对齐驱动，再执行上面 2）。

---

## 时间线（便于对照日志）

1. 全精度 PyTorch + CPU offload → 长段超时  
2. 换 27B-Q8 GGUF 多卡 → 仍超时  
3. 发现驱动 mismatch → reboot 对齐  
4. 仍超时 → 发现跨线程 + 队列堵塞；加超时与同池  
5. 仍卡同一 `len=166` 段 → 定位 **术语表 finalize 死循环** 并修复 → 同段带术语表约数秒成功  

若以后再出现「CPU 100% / GPU 0% / 某段必现」，优先怀疑：**术语表后处理**或**旧进程未杀掉**，其次才是驱动与跨线程。
