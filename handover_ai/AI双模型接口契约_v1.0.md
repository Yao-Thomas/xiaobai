# AI 双模型接口契约 v1.0

> 面向对象：负责「视觉模型 + 语言模型」的第三人
> 板端实现方：我们（Zynq-7020 / 领航者 V3.9）
> 目标：两个模型可插拔接入，互相不阻塞；最终把「融合结果」喂给语言模型和云端

---

## 0. 背景（先看这段，5 分钟）

我们已经在 Zynq PL 上跑了一个 **CNN 硬件加速器**（`cnn_conv_pool_q` @`0x43CD0000` + `cnn_fc` @`0x43CE0000`），
加载你之前交付的 `wave_weights.bin`（4480 B int8，8 类，test_acc 95.9%），
用 `wdens`（28×28 波形密度图）作为输入，**单次推理约 10~140 ms**。

现在要升级成**三模型协同**：

```
示波器采样（4096 点 @20MSPS）
        │
        ├──→ [模型A] 本地 PL CNN（我们维护，28×28，8 类）      ──┐
        │                                                      ├──→ [融合] → 统一结果 R
        ├──→ [模型B] 你的视觉模型（更多类别 / 更高精度）        ──┘
        │
        └──→ [特征提取] 频率 / 峰峰值 / 占空比 / 边沿 / 频谱…  ──→ [融合] → R
                                                                    │
                                          ┌─────────────────────────┴──────────────────────┐
                                          ▼                                                ▼
                            [模型C] 你的语言模型（本地语音输出）              云端 /intent（DeepSeek）
                            输入 R → 输出中文分析，TTS 播报                  输入 R → 输出更准的分析
```

**我们不需要你改板端代码，只需要你提供上图的「模型B」和「模型C」。**

---

## 1. 整体约定（两个模型都遵守）

### 1.1 传输格式
- 一律 **HTTP + JSON**（UTF-8，无 BOM）
- 服务监听 `0.0.0.0`，端口由你定（我们会在配置里填）
- 单次请求超时上限：**视觉模型 ≤ 800 ms，语言模型 ≤ 8 s**
- 失败必须返回 **HTTP 200 + `{"ok": false, "error": "..."}`**（不要用 4xx/5xx，板端网络栈较弱）

### 1.2 通用响应外壳
```json
{
  "ok": true,
  "engine": "你的模型标识，如 vision_v1 / llm_v1",
  "elapsed_ms": 123,
  "error": null
}
```

---

## 2. 【模型B】视觉模型接口

### 2.1 端点
```
POST http://<host>:<port>/waveform/classify
Content-Type: application/json
```

### 2.2 请求体
```json
{
  "type": "waveform",
  "fs": 20000000,
  "dec": 10,
  "samples": [512, 513, 515, ...],
  "hint": {
    "triggered": true,
    "vpp_lsb": 920,
    "freq_hz": 998.5,
    "duty_pct": 49.9,
    "channel": 0
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `samples` | int 数组 | **原始 ADC 码值，0~1023，长度 4096**（时间顺序：最老 → 最新） |
| `fs` | int | 基础采样率（固定 20000000） |
| `dec` | int | 抽取倍率（1~64；`有效采样率 = fs/dec`） |
| `hint` | object | 可选，板端已算好的粗测量值，可用于辅助判断 |

> **可选替代输入**：如果你更希望收「图像」而不是原始点，
> 可以在请求里改传 `"image_u8": [...]`（28×28=784 个 uint8，行 0 = 顶部 = 高电平），
> 我们会用现成的 `waveform_ai.wdens_u8()` 生成。**两种输入你选一种，我们在配置里切。**

### 2.3 响应体（**必须**是这个结构）
```json
{
  "ok": true,
  "engine": "vision_v1",
  "elapsed_ms": 42,
  "label": "square",
  "label_cn": "方波",
  "confidence": 0.973,
  "classes": ["sine", "square", "triangle", "sawtooth", "pulse", "step",
              "am", "fm", "noise", "clipping", "signal_loss", "duty_abnormal"],
  "probs": [0.001, 0.973, 0.004, 0.002, 0.006, 0.001,
            0.002, 0.001, 0.003, 0.003, 0.002, 0.002],
  "extra": {
    "notes": "可选：模型对这段波形的补充说明"
  }
}
```

**硬性要求：**
1. `classes` 与 `probs` **长度必须一致**，且 `probs` 之和 ≈ 1.0
2. `probs` 顺序 = `classes` 顺序（**不要按概率排序！**）
3. `confidence` = `probs[argmax]`
4. **`classes` 必须包含模型A 的那 8 个名字**（哪怕你只是透传概率 0），这样融合才好做：
   `sine, square, triangle, sawtooth, noise, clipping, signal_loss, duty_abnormal`
5. 你要新增的类别**追加在后面**，命名用小写英文 + 下划线

### 2.4 健康检查
```
GET http://<host>:<port>/health
→ {"ok": true, "engine": "vision_v1", "classes": [...], "input": "samples|image_u8"}
```

---

## 3. 【模型C】语言模型接口

### 3.1 端点
```
POST http://<host>:<port>/waveform/explain
Content-Type: application/json
```

### 3.2 请求体（**这就是「融合结果 R」**）
```json
{
  "type": "waveform_analysis",
  "result": {
    "label": "square",
    "label_cn": "方波",
    "confidence": 0.973,
    "fusion": {
      "local_cnn":   {"label": "square", "confidence": 0.731},
      "vision_model":{"label": "square", "confidence": 0.973},
      "agree": true,
      "final_source": "vision_model"
    },
    "measurements": {
      "freq_hz": 998.5,
      "vpp_v": 1.008,
      "vmax_v": 0.420,
      "vmin_v": -0.577,
      "duty_pct": 49.9,
      "offset_v": -0.078,
      "rise_us": null,
      "fall_us": null
    },
    "quality": {
      "triggered": true,
      "stale": false,
      "lost_frames": 23669,
      "dec": 10
    },
    "channel": 0,
    "ts": 1761000000.123
  },
  "style": {
    "max_chars": 70,
    "language": "zh-CN",
    "tone": "concise",
    "for_voice": true
  }
}
```

### 3.3 响应体
```json
{
  "ok": true,
  "engine": "llm_v1",
  "elapsed_ms": 1200,
  "text": "方波，占空比 49.9%，峰峰 1.01V，无明显削顶，基本正常。",
  "confidence": 0.9,
  "tts_ready": true
}
```

**硬性要求：**
1. `text` 是**纯文本**（不要 Markdown / 不要列表 / 不要 emoji），长度 ≤ `style.max_chars`
2. `text` 必须能直接交给 TTS 朗读（不会念出奇怪符号）
3. `for_voice: true` 时按"口语化一句话"输出

### 3.4 健康检查
```
GET http://<host>:<port>/health
→ {"ok": true, "engine": "llm_v1", "model": "你的模型名"}
```

---

## 4. 我们这边（板端）已有的能力（你可以直接调）

| 能力 | 端点 / 接口 | 说明 |
|---|---|---|
| 波形采样 | 板内 Python API | `ScopeDual().read_frame_locked()` → `(ch1, ch2, info)`，`ch1/ch2` 是 4096 点数组 |
| 本地 CNN 推理 | `infer_local.infer_waveform(samples)` | 返回和 §2.3 **同结构**（`label/confidence/classes/probs`） |
| 云端 LLM | `POST 127.0.0.1:8765/intent` | `{"system": "...", "text": "..."}` → `{"reply": "..."}`，实测 1.5~6.6 s |
| 语音合成 | `POST 127.0.0.1:8765/tts` | TTS 播报 |
| 测量值 | PL 硬件寄存器 | 频率/峰峰值/占空比等，误差 ≤0.3% |

**★ 重要：`infer_local.infer_waveform()` 的返回结构就是模板**，你的视觉模型按它来，融合代码零改动。

---

## 5. 融合策略（我们实现，你只需知道规则）

```python
# 伪代码
def fuse(local, vision):
    if vision.ok and not local.ok:      return vision
    if local.ok and not vision.ok:      return local
    if not local.ok and not vision.ok:  return None
    if local.label == vision.label:                    # 一致 → 加权平均置信度
        conf = 0.4*local.conf + 0.6*vision.conf
        return {label: local.label, confidence: conf,
                agree: True, final_source: "both"}
    # 不一致 → 谁的置信度高取谁，但把另一个作为候选
    return {label: vision.label if vision.conf > local.conf else local.label,
            confidence: max(...), agree: False,
            candidates: [local.label, vision.label]}
```

**→ 融合结果 R 会同时喂给：**
1. 你的**语言模型**（§3）
2. **云端** `/intent`（作为 `system` 提示词里的上下文，让云端分析更准）
3. 示波器 UI（卡片显示）和语音播报

---

## 6. 交付物清单

| # | 交付物 | 格式 | 备注 |
|---|---|---|---|
| 1 | 视觉模型服务 | 可启动的 HTTP 服务（Docker / Python 脚本 / 可执行文件均可） | 必须实现 §2 的 3 个端点 |
| 2 | 视觉模型权重 | `.bin` / `.pt` / `.onnx` | 便于我们备份和复现 |
| 3 | 语言模型服务 | 可启动的 HTTP 服务 | 必须实现 §3 的 3 个端点 |
| 4 | 模型卡片 | 一页 markdown | 类别定义、训练数据来源、精度、已知局限 |
| 5 | 测试数据 | 至少 20 条真实波形 + 标注 | 用于联合验收 |
| 6 | 启动脚本 | `run_vision.sh` / `run_llm.sh` | 端口、依赖、启动命令 |

**★ 如果你不想跑服务，也可以只给权重 + 推理脚本**，我们集成到 PC 端 exe（见 §7）。

---

## 7. 部署方式（三选一，你定）

| 方式 | 视觉模型跑在哪 | 语言模型跑在哪 | 优缺点 |
|---|---|---|---|
| **A. 云端服务** | 你的服务器 / 云主机 | 同左 | 板子只需联网，**最省板子算力**；延迟取决于网络 |
| **B. PC 端 exe 内** | 系统管家小白（Windows） | 同左 | 局域网内低延迟；需要 PC 常开 |
| **C. 板端本地** | Zynq PS（Python） | 同左 | 完全离线；但板子只有 2 核 A9、972 MB，只能跑小模型 |

**我们建议 A 或 B**（板端已经有 PL CNN 兜底，本地不需要跑大模型）。

---

## 8. 联合验收测试

```bash
# 1. 视觉模型健康检查
curl http://<host>:<port>/health

# 2. 用我们提供的真实波形测一次
curl -X POST http://<host>:<port>/waveform/classify \
     -H 'Content-Type: application/json' \
     -d @test_wave_square.json

# 3. 语言模型
curl -X POST http://<host>:<port>/waveform/explain \
     -H 'Content-Type: application/json' \
     -d @test_result_R.json

# 4. 端到端：板子上点「AI 分析」→ UI 显示融合结果 → 语音播报
```

**验收标准：**
- 视觉模型：我们提供的 20 条真实波形，准确率 ≥ 90%
- 语言模型：输出 ≤70 字、纯文本、能直接 TTS、语义正确
- 端到端：从点按钮到语音播报 ≤ 10 s

---

## 9. 联系与变更

- 契约版本：**v1.0**（2026-10-21）
- 字段只增不改；新增字段必须可选（板端忽略未知字段）
- 破坏性变更需双方确认后升版本号

---

## 附录 A：我们现在能提供的真实波形（用于你训练/验证）

板子可直接采集并导出：

```
采集格式：JSON
{
  "samples": [4096 个 int，0~1023],
  "fs": 20000000,
  "dec": 10,
  "label": "square",          ← 标注（人工确认后填）
  "meta": {"freq_hz": 998.5, "vpp_v": 1.008, "duty_pct": 49.9}
}
```

**告诉我们你希望标注哪些类别、每类要多少条、波形参数范围（频率/幅度/占空比），
我们按清单采集并打包给你。**

---

## 附录 B：现有 8 类的定义（供你扩类参考）

| 英文 | 中文 | 判定要点 |
|---|---|---|
| `sine` | 正弦波 | 连续平滑、对称 |
| `square` | 方波 | 高低电平跳变、边沿陡直 |
| `triangle` | 三角波 | 上升/下降均匀、峰尖 |
| `sawtooth` | 锯齿波 | 单向扫描、一侧缓一侧陡 |
| `noise` | 噪声 | 无周期 |
| `clipping` | 削顶 | 峰顶被限幅 |
| `signal_loss` | 丢信号 | 平线或强衰减 |
| `duty_abnormal` | 占空比异常 | 高低占比失衡（非 50%） |

**建议你新增（我们讨论过的）：** `pulse` 脉冲 / `step` 阶跃 / `am` 调幅 / `fm` 调频 / `ringing` 振铃
