# 06 · 任务 D：本地 agent 模型（LoRA / RAG）与板端可行性结论

> 验收标准（任务书）：**① 量化后能在板端加载（或明确决定走云端）② 在项目领域问题上回答质量可接受**
> 任务书还特别要求一条**诚实的提醒**：
> "竞赛项目的对话数据量（几百~几千条）微调出来的模型，**效果大概率不如"大模型 + RAG"**"
> **详细实现说明见 `src/agent/README.md` 与 `src/agent/feasibility.md`。**

---

## 1. ★ 板端可行性结论（明确，不模糊）

> **0.5B INT4 权重约 250 MB，但开发板只有 1 GB RAM**，
> 且已跑完整 Ubuntu 桌面 + 音频服务 + agent；
> 叠加 Python / transformers 运行时与 KV cache **必然 OOM**。
>
> **⇒ 明确决定：本地 agent 模型走云端，板子只做转发；
> 本地保留纯标准库 RAG（几十 MB）作为离线降级。**

这条结论直接支撑了任务 G/H 的分级推理设计
（`docs/04_云端推理API与降级.md`）。

---

## 2. 已交付并**实测**的部分

### 2.1 RAG 知识库

从项目全部文档（交接包 11 篇 + 本项目 docs + 上一轮 CNN 交接文档 + 源码 docstring）
构建，**551 个 chunks**，平均 278 字，每块带 `source` 与 `title_path` 元数据。

### 2.2 RAG 基线指标（★ 实测，非估计）

| 指标 | 值 |
|---|---|
| 测试集 | 65 条（53 可答 + 12 应拒答） |
| **要点命中率**（keypoint recall） | **0.5825** |
| **来源命中率** | **0.7170** |
| **拒答准确率** | **0.9231** |
| 幻觉率（回答了本应拒答的问题） | 0.3333 |

检索是**纯标准库**实现的 BM25 + 中文 bigram（不依赖 jieba / rank_bm25），
并带**拒答机制**（检索得分低于阈值就回答"不在知识范围内"）。

### 2.3 LoRA 指令数据集

**857 条**（792 grounded + 65 拒答），train 772 / val 85，
sharegpt 风格，每条带 `source` 可溯源。

**★ 数据集里刻意包含"文档里没有答案"的样本**（如"今天天气怎么样"），
用来训练模型学会说"不知道" —— 这对抑制幻觉很关键，也是评测的一部分。

### 2.4 单元测试

```bash
python -m unittest discover -s src/agent/tests -t .
# Ran 25 tests ... OK
```
（纯标准库，在**没有 torch 的机器上**也能全部通过。）

---

## 3. ★★ 三条路线的实测对比（任务书要求的"诚实对比"，已真跑）

`src/agent/compare_rag_vs_lora.py` 用**同一份 65 条测试集**评了三条路线，
**LoRA 已在 lab415 上真的训练并评测**（不是估计、不是借用别人的经验）：

| 路线 | 要点命中率 | 来源命中率 | 拒答准确率 | 幻觉率 |
|---|---|---|---|---|
| **纯 RAG**（标准库 BM25） | **0.573** | **0.717** | **0.938** | **0.250** |
| LoRA 微调（Qwen2.5-0.5B） | 0.058 | 0.000 | 0.815 | **1.000** |
| RAG + LoRA | 0.330 | 0.057 | 0.738 | 0.500 |

### ★ 结论：完全印证、而且比任务书的提醒更严厉

任务书原话：

> **竞赛项目的对话数据量（几百~几千条）微调出来的模型，效果大概率不如"大模型 + RAG"。**

实测把这个提醒变成了本项目的硬数据：

- **LoRA 的要点命中率只有 0.058（RAG 的 1/10），幻觉率 100%** ——
  772 条领域数据微调出的 0.5B 模型，**几乎对所有问题都在编**；
- **RAG + LoRA 反而比纯 RAG 更差**（要点 0.573→0.330，幻觉 0.25→0.50）——
  把微调模型接进链路是**负收益**。

**⇒ 最终建议（有实测支撑）**：
**云端走纯 RAG**；LoRA 模型作为"我们有自研模型"的**演示件**保留，
**不要接进生产链路**。

**★ 这个负面结果本身就是有价值的交付物**：它用本项目自己的数据量级（772 条）
证明了"小数据微调不如 RAG"，而不是靠引用别人的经验。

### LoRA 训练的实际配置与产物（真跑）

| 项 | 值 |
|---|---|
| 基座 | `Qwen/Qwen2.5-0.5B-Instruct` |
| 数据 | 772 train / 85 val |
| 超参 | 3 epoch，batch 4，grad-accum 8，lr 2e-4，LoRA r=16 α=32 dropout 0.05，bf16 |
| 可训练参数 | **8,798,208 / 502,830,976（1.75%）** |
| 产物 | `lora_model/adapter/`、`lora_model/merged/`（988 MB safetensors）、`hyper.json` |

### 量化实测（真跑，不是估算）

| 项 | 值 |
|---|---|
| int8 体积（含 scale） | **472.8 MB** |
| **int4 体积（含 scale）** | **250.3 MB** |
| int8 相对 MSE | 9.685e-05 |
| int4 相对 MSE | 1.652e-02 |
| 16-token 前向延迟 | 691.0 ms（cuda） |
| **GPU peak 显存** | 2839.4 MB |
| **进程 RSS** | **3360.4 MB** |

**⇒ 板端可行性结论（现在是实测而非分析）**：
INT4 权重只有 250 MB，但**运行时进程 RSS 是 3.36 GB** ——
1 GB 的板子上**根本没有余量**。
`lora_model/quant/feasibility.md` 已由脚本自动回填这些实测数字。

### 跑通这条链路踩掉的 transformers 5.x 兼容坑（共 5 个，已全部修）

实验室环境是 **transformers 5.15.1**（2026 版），与 4.x 的 API 有实质差异。
这些都是"只有真跑才会暴露"的问题，已修好并留在代码注释里：

| # | 症状 | 修复 |
|---|---|---|
| 1 | `to_messages()` 把 list 当 dict 索引 → `TypeError` | 兼容两种入参 |
| 2 | `TrainingArguments(warmup_ratio=...)` → 5.x 已删除该参数 | 按实际签名过滤 kwargs，4.x/5.x 都能跑 |
| 3 | `DataCollatorForSeq2Seq` → `ValueError: type of {...} unknown: <class 'dict'>` | 自己写 `PadCollator`，与版本无关 |
| 4 | 缺少 `attention_mask` 列 | `tokenize_fn` 显式产出 |
| 5 | `apply_chat_template(tokenize=True)` 返回 **dict/BatchEncoding** 而非 `list[int]` | 先判类型再取值 |

另外还有一个**环境级**根因值得记下来：
**pip 的临时目录默认在 `/tmp`，而 lab415 根分区已满** ——
`datasets`/`pyarrow` 一直装不上、报 `No space left on device`，
把 `TMPDIR` 指到 `/data` 就解决了。

---

## 4. 一键复现

```bash
bash scripts/run_agent.sh          # 建语料 → RAG 基线评测 → LoRA 训练 → 量化 → 三路线对比
SMOKE=1 bash scripts/run_agent.sh  # 冒烟
```

**★ 注意**：`build_corpus.py` 需要项目文档目录。
本仓库已把源文档放进 `corpus/`，远端脚本会自动搭一个 `corpus_root`
（因为 `os.walk` 默认不跟随符号链接，所以用真实拷贝）。
