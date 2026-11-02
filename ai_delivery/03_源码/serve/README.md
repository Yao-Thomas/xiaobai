# src/serve —— 云端推理 API（任务 G）+ 分级推理 + 分布式 agent 同步（任务 H）

> 项目：系统管家小白（Zynq-7020 板载自主助手）· 2026 嵌入式芯片与系统设计竞赛
> 依据：`07_接口约定单.md` 接口④、`06_分工总表_核对版.md` 第②节第 7/8 项、`00_接口冻结单.md` §6

## 1. 目录与职责

| 文件 | 作用 | 依赖 |
|---|---|---|
| `config.py` | 所有可调参数（端口、api_key、超时 2.5s、阈值 0.7、模型目录…），支持 `SERVE_*` 环境变量覆盖 | 仅标准库 |
| `model_backend.py` | 模型后端抽象 + 量化模型加载器（纯 numpy int8 前向）+ 启发式占位回退 | numpy + 标准库 |
| `router.py` | ★ 分级推理核心 `route(request, local_predict, cloud_predict)`，纯函数 | 仅标准库 + config |
| `sync_store.py` | 任务 H 云端同步存储（增量 + 时间戳 + PC 为准），纯 sqlite3 | 仅标准库 |
| `client.py` | 板端/PC 端调用客户端（超时/重试/降级标志） | 仅标准库 urllib |
| `api.py` | FastAPI 应用：`/infer` `/health` `/metrics` `/sync/push` `/sync/pull` | fastapi/uvicorn |
| `demo_offline.py` | ★ 现场"拔网线"降级演示脚本 | 仅标准库 |
| `bench_latency.py` | 延迟基准，输出 p50/p95/max，验证 < 3 s | 仅标准库 |
| `tests/` | 纯标准库 unittest（无 fastapi 也能跑） | 仅标准库 |

核心逻辑（`router`/`sync_store`/`client`）**不依赖 fastapi**，可在开发机（无 fastapi）上单测。

## 2. 怎么起服务（lab415）

```bash
bash scripts/run_serve.sh                       # 默认 0.0.0.0:8000
SERVE_PORT=8001 bash scripts/run_serve.sh       # 换端口
SERVE_API_KEY=your-secret bash scripts/run_serve.sh   # 开启 api_key 鉴权
```

等价手动命令：

```bash
cd src/serve
/data/pengyc_fzu/envs/fpga2026/bin/python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

健康检查与指标：

```bash
curl http://<云端地址>:8000/health
curl http://<云端地址>:8000/metrics
```

## 3. 接口 schema（与契约逐字一致）

### 3.1 `POST /infer`（接口④）

请求：

```json
POST /infer
Content-Type: application/json
{
  "type": "waveform" | "chat",
  "data": [ ... ],
  "hint": "可选提示",
  "api_key": "..."
}
```

- `type="waveform"` 时 `data` 支持两种形态（用 `hint` 或 `data` 长度自动判别）：
  - **4096 个 0~255 原始采样**（最常见）→ 复用 `src/common/preprocess.py` 的 `capture_to_image(..., mode="wdens")` 变 28×28 → 再推理；
  - **784 个 int8/uint8 图像像素** → 直接推理。
  判别结果会写进响应 `detail.interpretation`。

成功响应 200：

```json
{
  "ok": true,
  "label": "square",
  "confidence": 0.93,
  "detail": { },
  "elapsed_ms": 240
}
```

失败/超时：

```json
{ "ok": false, "error": "描述" }
```

说明：`/infer` 是**云端侧**推理，返回严格契约字段。分级决策（本地→云端、离线降级）由板端 `router.py` 完成，见 §4。

### 3.2 `POST /sync/push`（任务 H）

```json
{
  "client_id": "pc" | "board",
  "records": [
    { "record_id": "uuid", "ts": 1728000000.0, "payload": { ... } },
    ...
  ],
  "api_key": "..."
}
```

响应：

```json
{
  "ok": true,
  "accepted": ["uuid1", ...],
  "rejected": [ { "record_id": "uuid2", "reason": "conflict: ..." }, ... ],
  "server_seq": 42
}
```

### 3.3 `GET /sync/pull`（任务 H）

```
GET /sync/pull?client_id=board&since=0&limit=50&api_key=...
```

响应：

```json
{
  "ok": true,
  "records": [ { "record_id": "...", "origin": "pc", "client_ts": 1728000000.0,
                 "payload": { }, "server_seq": 12, "updated_at": 1728000001.0 }, ... ],
  "server_seq": 12
}
```

`server_seq` 是服务端单调递增游标：客户端把上次返回的 `server_seq` 作为下次 `since`，即可增量同步。

## 4. 分级推理与降级（契约固定，必须能演示）

```
板子侧策略:
  ① 优先用本地量化小模型
  ② 置信度 < 阈值（0.7）或请求类型未知 → 送云端
  ③ ★ 云端不可达 / 超时（2.5s）→ 降级到本地，明确提示"离线模式"
  ④ 联网后自动恢复（每次请求独立判断，无需重启服务）
```

`router.route(request, local_predict, cloud_predict)` 把上述策略实现为纯函数，返回的 `detail.decision_path` 可取：

| decision_path | 含义 |
|---|---|
| `local` | 本地置信度 ≥ 阈值，未走云端 |
| `cloud` | 送云端且云端成功 |
| `cloud_fallback_local` | 云端失败，降级回本地（`offline_mode=true`） |

响应顶层恒带 `offline_mode`（bool），板端据此直接判断是否提示"离线模式"。

### 降级现场演示

```bash
python src/serve/demo_offline.py
```

脚本会：启动内置"云端" → 正常请求（走 `cloud`）→ 把客户端指向不可达地址 `127.0.0.1:9` + 0.3s 超时模拟拔网线（走 `cloud_fallback_local`，打印"离线模式"）→ 恢复（自动回到 `cloud`）。全程无 fastapi 依赖，任何机器都能跑，输出可直接进演示视频。

## 5. 任务 H：同步约定与冲突处理规则

| 约定 | 规则 |
|---|---|
| 谁为主 | **PC 端为主**（权威） |
| 板子缓存 | 板子本地只存最近 **N** 条（`config.BOARD_RECENT_N`，默认 50；`/sync/pull?limit=N` 或 `pull_recent`） |
| 同步方式 | 增量同步：服务端单调 `server_seq` 做游标，客户端记上次游标即可 |
| 时间戳 | 每条记录带 `client_ts`（客户端产生时间），服务端另记 `updated_at` |
| 冲突 | **以 PC 为准**：同一 `record_id` 若已存在且权威作者是 `pc`，板子 push 被拒绝（`rejected`）；PC 的写入始终覆盖 |
| 板子离线 | 存储完全在云端，PC 的 push/pull **不依赖板子在线** |

冲突裁决实现要点（`sync_store.push`）：
- `pc` push → 总是接受（`origin` 更新为 `pc`，覆盖一切）；
- `board` push → 仅当记录不存在、或现有记录的 `origin == "board"` 时才接受；否则拒绝（PC 为准）。

## 6. 模型后端与回退

- 若 `deliverables/quantized_model/` 存在（含 `model_spec.json` + `weights.bin`），自动加载，跑**纯 numpy int8 前向**（与 `qmodel.reference_infer_arrays` 逐位一致，不依赖 torch）。
- 若不存在，用内置**启发式占位分类器**（简单统计特征），保证 API 始终能跑。占位分类器对常规波形故意给出 **< 0.7 的置信度**，从而触发送云端（这恰好是分级推理要演示的路径）。
- 预处理复用冻结契约 `src/common/preprocess.py`（`capture_to_image(..., mode="wdens")`）；import 失败会优雅降级为 `ok:false`，不让服务崩。
- ★ 注意：任务书指定预处理 `mode="wdens"`；若最终交付的 `model_spec.json` 声明了不同 `input_type`（如 `stft`），改 `config.PREPROCESS_MODE` 或设环境变量 `SERVE_PREPROCESS_MODE=stft` 即可（一行改动）。

## 7. 客户端用法（板端 / PC 端）

```python
from client import InferClient

cli = InferClient("http://<云端地址>:8000", api_key="...", timeout=2.5, retries=1)
resp = cli.infer("waveform", samples)        # 4096 个 0~255 采样
if not resp.get("ok"):
    print("云端失败/离线:", resp.get("error"))
```

网络不可达/超时会返回 `{"ok": false, "error": "...", "offline": true}`（`offline` 即降级标志）。

## 8. 测试

核心逻辑测试（**无 fastapi 也能跑**）：

```bash
cd ai_training
python -m unittest discover -s src/serve/tests -t .
```

覆盖：`router`（分级路由/离线降级/异常兜底）、`sync_store`（增量同步/PC 为准冲突/板子缓存）、`client`（超时/降级标志）。

延迟基准（验收 < 3 s）：

```bash
python src/serve/bench_latency.py --local --n 200          # 直接压后端
python src/serve/bench_latency.py --url http://<云端>:8000 --n 200   # 端到端
```

## 9. 健壮性与并发

- 任何异常都转成 `{"ok": false, "error": "..."}`，绝不 500 崩溃（`/infer`、`/sync/push`、`/sync/pull` 均有兜底）。
- 简单鉴权：`api_key` 从 `config.API_KEY` 读（`SERVE_API_KEY` 覆盖）；未配置时不校验并打日志警告。
- 并发：FastAPI 里的阻塞调用（模型前向 / sqlite）放进线程池（`run_in_threadpool` / 同步 `def` 端点），不阻塞事件循环。
