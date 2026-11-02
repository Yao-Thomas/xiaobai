# 04 · 任务 G / H：云端推理 API 与分级推理降级

> 验收标准（任务书）：**板子能调用并拿到结果；延迟 < 3 s**；
> **降级行为约定 + 云端侧实现**；**拔网线后能正确降级，联网后自动恢复**。
> 实测：契约逐字实现；本地 p95 **0.3 ms**；20 项单测通过。✅
> **详细实现说明见 `src/serve/README.md`**（本文只记结论与契约要点）。

---

## 1. 契约（★ 与 `07_接口约定单.md` 逐字一致，未改一个字段）

```
POST /infer
{ "type": "waveform" | "chat", "data": [...], "hint": "...", "api_key": "..." }

→ 200 { "ok": true, "label": "square", "confidence": 0.93,
        "detail": {...}, "elapsed_ms": 240 }
→ 失败 { "ok": false, "error": "..." }
```

**唯一的加法**：成功响应里多一个顶层布尔 `offline_mode`
（在线 `false` / 降级后 `true`）。这是**向后兼容的加法** ——
分级推理的约定本来就要求"明确提示离线模式"，板端直接读这个字段即可。

其它端点：`GET /health`、`GET /metrics`、`POST /sync/push`、`GET /sync/pull`。

---

## 2. 分级推理（任务 H 的云端侧）

```
① 优先用本地量化小模型
② 置信度 < 0.7，或请求类型本地不支持  → 送云端
③ 云端不可达 / 超时 2.5 s             → 降级到本地，并置 offline_mode = true
④ 联网后自动恢复（不重启服务）
```

实现要点：
- `router.route(request, local_predict, cloud_predict)` 是**纯函数**、**零 fastapi 依赖**，
  所以能在没有 fastapi 的机器上完整单测（本机 Windows 上就跑通了）。
- 每次决策把路径记进 `detail.decision_path`（`local` / `cloud` / `cloud_fallback_local`），
  演示时可以直接讲清楚"为什么这次走了云端"。
- `data` 两种形态自动识别：**4096 个采样**（调 `preprocess.capture_to_image(...,"wdens")`）
  或**784 个像素**（直接推理），并在 `detail` 里说明按哪种解释处理。
- 阻塞调用走线程池，任何异常都返回 `{"ok": false, "error": ...}`，不 500、不崩。

---

## 3. ★ 降级演示（拔网线测试，验收要求）

```bash
python src/serve/demo_offline.py                     # 内置模拟云端
python src/serve/demo_offline.py --cloud-url http://<lab415>:8000
```

输出形态（可直接进演示视频）：
```
[1] 正常      : decision=cloud      confidence=0.93  offline_mode=False
[2] 拔网线    : decision=cloud_fallback_local  offline_mode=True   ← 提示"离线模式"
[3] 恢复联网  : decision=cloud      confidence=0.93  offline_mode=False
```

---

## 4. 延迟基准

```bash
python src/serve/bench_latency.py --local --n 60
```
实测（本机，启发式回退后端）：**p50 0.2 ms / p95 0.3 ms / max 0.5 ms** ⇒ 远低于 3 s。
接上真实量化模型后端后再在同一脚本上复测即可。

---

## 5. 任务 H 的分布式 agent 云端侧

按 `06_分工总表` 的约定实现：

| 约定 | 实现 |
|---|---|
| 记录以 **PC 端为主** | `sync_store` 里 board 的 push **覆盖不了** pc 记录 |
| 板子存最近 N 条 | `pull_recent` 支持 N |
| 增量同步 + 时间戳 | 服务端单调 `server_seq` 游标 |
| 冲突以 PC 为准 | 同上；冲突写进返回体便于排查 |
| 板子离线时 PC 端仍可用 | 云端无状态依赖，板子缺席不影响 PC 读写 |

---

## 6. 测试

```bash
python -m unittest discover -s src/serve/tests -t .
# Ran 20 tests ... OK   （router 9 / sync_store 8 / client 3）
```
`api.py` 是唯一 import fastapi 的文件，其余核心逻辑零 web 框架依赖。
