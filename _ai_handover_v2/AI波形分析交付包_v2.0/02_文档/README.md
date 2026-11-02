# AI 波形分析 v2.0 · 多模态波形分析系统

> 对应交接任务：《AI 波形模型升级任务 v1.0》（2026-10-21）+《AI 双模型接口契约 v1.0》
> 硬件：正点原子 领航者 ZYNQ7020 V3.9 + 3PA1030 双通道 AD（10 bit / 20 MSPS）
> 运行：**纯 CPU**，单帧视觉 7.7 ms，完整分析 p50 37 ms

---

## 0. 一句话

端侧 PL CNN 只能给"8 类 + 8 个概率"；本服务给它补上**「看得更细 + 说得更清 + 评质量 + 识未知」**：

```
4096 点原始采样（10 bit）
   ├─ 96×96×3 时幅图 ─┐
   ├─ 59 维可解释特征 ─┤→ 融合网络 → 16 类概率
   ├─ 端侧 8 类概率  ─┘
   ├─ 原始采样 → 质量评估（上升/下降/过冲/SNR/抖动/THD/占空比稳定度/评分）
   ├─ 嵌入+特征 → 未知异常检测（马氏距离 + 可解释规则）
   └─ 结构化事实 → 中文一句话（≤70 字，TTS 直接可读）
```

---

## 1. 验收结果速览

| 项目 | 结果 | 说明 |
|---|---|---|
| 契约结构 | **300/300 通过** | classes/probs 长度顺序、和为 1、label=argmax、text 纯文本 ≤70 字 |
| 16 类准确率 | **95.96%** | 仿真测试集 2500 条 |
| 端侧原 8 类 | **95.44%** | 同一批数据里的前 8 类子集 |
| 困难域准确率 | **83.3%**（验收口径；训练报告口径 87.7%） | 噪声 16~32 LSB、带宽 0.30~0.55 Nyq、增益 ±20% |
| 省略 `local_cnn` | **94.5%** | 端侧概率缺失时的自动降级 |
| 完整分析延迟 | **p50 37 ms / p95 42 ms** | 契约预算 800 ms；HTTP 环回实测 19.5 ms |
| 质量评估 | 上升时间误差 **≤0.5 µs**、SNR 相关 **−0.989** | 对已知阶跃/噪声的定量验证 |
| 异常检测 | 误报 **4.5%**、未知混合检出 **28%** | 距离 AUC 0.86；规则判据可解释 |
| 健壮性 | **5/5 通过** | 空/长度错/越界/缺字段/坏 JSON 均返回 ok:false |
| 模型体积 | 1.2 MB / 291 k 参数 | 纯 CPU 可跑 |

自动生成的验收报告：`runs/v2_full/acceptance/acceptance.md`

---

## 2. 快速开始

```powershell
# 环境（CPU 版 torch 即可）
pip install -r requirements.txt

# 启动服务（默认 0.0.0.0:8000，日志会打印板端该填的局域网地址）
.\scripts\run_service.ps1

# 另开一个窗口：健康检查 + 用夹具测一条
python -m wave_ai.client --url http://127.0.0.1:8000 --health
python -m wave_ai.client --url http://127.0.0.1:8000 --file deliverables/fixtures/test_wave_square_0.json
```

**从零复现模型**（约 15 分钟）：

```powershell
python scripts/gen_data.py --out data/ds_train --hard data/ds_hard `
       --train 12000 --val 2500 --test 2500 --hard-n 2500 --ood 600
python -m wave_ai.train --data data/ds_train --hard data/ds_hard `
       --out runs/v2_full --epochs 16 --limit 8000
python scripts/build_anomaly.py --run runs/v2_full --data data/ds_train
python -m wave_ai.acceptance --model runs/v2_full/model_bundle.pt `
       --anomaly runs/v2_full/anomaly_stats.npz --n 300
```

---

## 3. 目录结构

```
ai_waveform_v2/
├─ wave_ai/                 算法与服务（纯 Python，无 Web 框架）
│  ├─ config.py             类别表/物理常量（唯一真源，顺序冻结）
│  ├─ hw_sim.py             10 bit 真实链路仿真器（训练数据来源）
│  ├─ representation.py     4096 点 → 96×96×3
│  ├─ features.py           59 维可解释特征
│  ├─ quality.py            质量评估 DSP（方向 2）
│  ├─ anomaly.py            未知异常检测（方向 3）
│  ├─ explain.py            中文一句话（≤70 字，可外挂 LLM 润色）
│  ├─ model.py              CNN + 特征融合网络
│  ├─ train.py / dataset.py 训练与数据
│  ├─ finetune.py           真实 JSONL 微调（采集清单回来后用）
│  ├─ analyzer.py           单帧完整流水线
│  ├─ serve.py              HTTP 服务（4 个端点）
│  ├─ client.py             调用示例
│  └─ acceptance.py         联合验收自测
├─ scripts/                 数据生成/夹具/异常统计/启动脚本
├─ tests/                   23 个单测（契约/质量/表示/仿真）
├─ docs/                    模型卡片 / 接口说明 / 质量算法 / 异常检测 / 采集清单 / 交接报告
├─ deliverables/fixtures/   32 条测试请求 + 融合结果 R + JSONL 示例
└─ runs/v2_full/            模型、训练报告、验收报告
```

---

## 4. 四个端点

| 端点 | 用途 |
|---|---|
| `GET /health` | 健康检查、类别表、模型指标 |
| `POST /waveform/analyze` | **主接口**：识别 + 质量 + 异常 + 文本，一次调用 |
| `POST /waveform/classify` | 只要视觉分类（契约模型 B） |
| `POST /waveform/explain` | 输入融合结果 R，输出一句话（契约模型 C） |

示例（节选真实响应）：

```json
{"ok": true, "label": "square", "label_cn": "方波", "confidence": 0.983,
 "text": "方波，高低两电平，4.01千赫兹，峰峰5.48伏，占空比49.8%，质量良好78分，上升0.7微秒，抖动97纳秒。",
 "quality": {"score": 78, "rise_us": 0.684, "snr_db": 21.1, "thd_pct": 41.6, "jitter_ns": 97.0},
 "anomaly": {"is_anomaly": false, "features": [], "suggestion": ""},
 "elapsed_ms": 37}
```

接口细节见 **`docs/接口实现说明.md`**。

---

## 5. 关键设计判断（都不是拍脑袋）

1. **不做 VLM 微调，做"强视觉小模型 + 强测量 + 受控语言层"**
   —— 800 ms/断网/CPU 的硬约束下，VLM 不可行；事实本来就可算，语言层只需说准。理由与退路见模型卡片 §1。
2. **输入 96×96 而不是 28×28**
   —— K≈2（1 kHz@dec=10）时 28 列一个周期只有 14 列，形状被压平；96 列有 48 列/周期。
   但**边沿细节在图上仍不可见**（一列=21 µs），所以上升时间从原始采样算。
3. **三个视觉通道缺一不可**
   —— 绝对幅度（撞轨）、自归一化幅度（小信号）、局部残差（毛刺/窄脉冲）。
4. **59 维手工特征与 CNN 并列**
   —— 绝对量纲、窄事件强度、周期置信度在图上画不出来，必须显式给。
5. **端侧概率当"参考"不当"真值"**
   —— 训练时 25% 概率丢弃（填 1/8 均匀先验）；实测省略 local_cnn 仍 94.5%。
6. **质量指标按类别区分**
   —— 方波的 THD 天生 41%，用"THD 越低越好"会得出"标准方波 0 分"。
7. **异常阈值按类标定**
   —— 固定阈值会把 43% 的干净方波报成"毛刺"（方波边沿残差天生接近 1 倍半峰峰值）。

---

## 6. 已知限制（联调前必读）

1. **训练数据是仿真**（真实链路建模，但不是板卡实测）。域偏移下 87.7%，说明有鲁棒性但**不能替代真实微调**。
2. **`dec` 必须传对**——K/频率/时间类指标全依赖它；填错掉约 10 个点。
3. 时间分辨率 = 1 个采样间隔（dec=10 时 0.5 µs）。
4. 抖动/占空比稳定度需要 ≥4 个周期；dec=10、1 kHz 时窗口只有 2 个周期 ⇒ 返回 null（不编数字）。
5. `glitch` 在 dec=10 下只能看到 1~6 µs 的尖峰；更窄的归 PL 硬件检测器。
6. 未知异常对"两类混合"检出率 28%；对结构性未知（三音/扫频）未评估。
7. `image_u8`（28×28）输入不支持，请传 `samples`。

---

## 7. 下一步（等你们的数据）

1. 按 **`docs/数据采集清单.md`** 采 8+8 类真实数据（优先 square/sine/duty_abnormal/glitch/ringing）；
2. `python -m wave_ai.finetune --real real_ds --model runs/v2_full/model_bundle.pt --out runs/v2_real`
3. 用 `acceptance.py --url` 对真板联调（契约 + 延迟 + 文本长度）；
4. 把 `runs/v2_real/model_bundle.pt` 换进服务，接口不变。
