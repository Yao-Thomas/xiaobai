# 任务 D：模型① —— 本地 agent 用的小语言模型

> 项目：系统管家小白 —— Zynq-7020 板载自主助手
> 负责：AI 训练负责人
> 本目录：`ai_training/src/agent/`

## 0. ★ 先看结论（任务书要求的那条"诚实的提醒"）

竞赛项目的对话数据只有**几百~几千条**，用它微调出来的小模型，**效果大概率不如「大模型 + RAG」**。所以两条路的取舍是：

| 路线 | 优点 | 缺点 | 适合 |
|---|---|---|---|
| **RAG（检索增强）** | 回答可溯源、不会瞎编领域外内容、纯标准库、几十 MB 内存 | 只能"抽取/拼"已有句子，不会组织新句子；检索错了就答错 | **要"效果最好"** |
| **LoRA 微调** | 可以说"我们有自研模型"、能生成新句子、离线端到端 | 数据太少 → 过拟合、爱幻觉；0.5B 模型板端跑不动（见 §4） | **要"自研模型"这个说法** |

**本项目的明确决定：走云端，板子只做转发；本地用纯标准库 RAG 做离线降级。**
（理由见 §4 板端可行性结论。）

---

## 1. 文件清单

| 文件 | 作用 | 依赖 |
|---|---|---|
| `build_corpus.py` | 从项目文档构建 RAG 知识库 + LoRA 指令数据集（≥800 条） | 纯标准库 |
| `rag.py` | ★ 纯标准库 RAG：BM25 + 中文 bigram 分词 + 拒答机制 | 纯标准库 |
| `eval.py` | ★ 纯标准库评测：内置 65 条领域测试集（53 可答 + 12 应拒答）+ 四项指标 | 纯标准库 |
| `quantize_llm.py` | INT8 / INT4 量化 + 显存实测 + `feasibility.md` | torch |
| `train_lora.py` | LoRA 微调 Qwen2.5-0.5B-Instruct | torch/peft/transformers |
| `compare_rag_vs_lora.py` | 同一测试集对比 RAG / LoRA / RAG+LoRA（诚实对比） | torch 可选 |
| `tests/` | 纯标准库 unittest（无 torch 可跑） | 标准库 |
| `feasibility.md` | 板端可行性结论（分析值 + 实测回填位） | — |

---

## 2. RAG 怎么用（本地、无需 torch）

```bash
# ① 构建知识库 + 指令数据（需要项目文档在上级目录，见 §5）
cd ai_training/src/agent
python build_corpus.py

# ② 评测 RAG 基线（生成 eval_report.json / eval_report.md）
python eval.py

# ③ 直接问答
python - <<'PY'
from rag import RAG, load_chunks
r = RAG(load_chunks("kb/chunks.jsonl"))
print(r.answer("ES8388 的 DAC 音量寄存器是多少"))
print(r.answer("CNN 量化公式是什么"))
print(r.answer("今天天气怎么样"))   # → 拒答
print(r.build_prompt("CNN 量化公式是什么"))  # 有 LLM 时把检索结果塞进 prompt
PY
```

### 实测基线（本机 Windows，无 torch，真实输出）

`python eval.py` 的实测指标（53 可答 / 12 应拒答，共 65 条）：

| 指标 | 实测值 |
|---|---|
| 要点命中率 keypoint_recall | **0.573** |
| 来源命中率 source_hit_rate | **0.717** |
| 拒答准确率 refusal_accuracy | **0.938** |
| 幻觉率 hallucination_rate | **0.250** |

> 说明：要点命中率 0.56 是**纯抽取式、无 LLM** 的上限附近水平 —— 它只能"从文档里拼句子"，
> 拼不出自然的新句子。这正是"RAG + 大模型"比"纯 RAG"更强的点：把 §2 里
> `build_prompt()` 的上下文喂给大模型，让它组织语言，命中率会显著更高。
> 幻觉率 0.25 的 3 条漏网（"世界杯""手机坏了""电影推荐"）是因为它们与语料有表面词重合
> （"我的世界"游戏、"手机热点"、"好看"），纯 BM25 无法做语义判断 —— 这只有 LLM 能拦住。

---

## 3. LoRA 怎么训（服务器 lab415）

环境已装好（`torch 2.5.1+cu118 / transformers 4.46.3 / peft 0.13.2 / datasets 3.1.0`）。

```bash
ssh lab415
cd /data/pengyc_fzu/fpga2026_ai
PY=/data/pengyc_fzu/envs/fpga2026/bin/python

# ① 构建语料（若项目文档已同步到服务器；否则用仓库里已提交的 kb/ + lora_data/）
cd src/agent && $PY build_corpus.py

# ② LoRA 微调（模型缓存强制放 /data，不用默认 ~/.cache）
$PY train_lora.py --data lora_data --out lora_model --epochs 3 --seed 20261001

# ③ 量化 + 显存实测 + feasibility.md
$PY quantize_llm.py --model lora_model/merged --out lora_model/quant
# SMOKE（不下载权重，随机小模型验证代码通路）：
$PY quantize_llm.py --dummy --out lora_model/quant

# ④ 三条路线诚实对比
$PY compare_rag_vs_lora.py --kb kb/chunks.jsonl --lora-model lora_model/merged
```

### 关键超参（`train_lora.py` 默认，落盘到 `lora_model/hyper.json`）

- 基座 `Qwen/Qwen2.5-0.5B-Instruct`，LoRA r=16 / alpha=32 / dropout=0.05
- 目标模块：q/k/v/o_proj + gate/up/down_proj；lr=2e-4，warmup 3%，bf16
- 固定种子 20261001，数据 = `lora_data/{train,val}.jsonl`（sharegpt 风格，含拒答样本）

---

## 4. ★ 量化结论 + 板端可行性（明确决定）

### 量化体积（分析值，参数按 Qwen2.5-0.5B ≈ 0.49B）

| 精度 | 权重体积 | 说明 |
|---|---|---|
| bf16 | ≈ 980 MB | 原始 |
| INT8（per-channel） | ≈ 490 MB + scale | weight-only |
| INT4（group_size=128） | **≈ 245 MB + scale(~8 MB)** | 任务书写的"约 350 MB"偏保守 |

### 板端能不能加载？（1 GB RAM 硬约束）

```
板子总内存        1 GB
系统基线（Ubuntu 桌面 + 音频服务 + agent + GPU 驱动）  ≈ 500~650 MB
可用余量          ≈ 350~500 MB
0.5B INT4 权重    ≈ 250 MB   ← 光权重就吃掉大半余量
+ transformers/Python 运行时 + KV cache + 激活      ≈ 数百 MB
⇒ 几乎必然 OOM，且首 token 延迟（双核 A9 无 NPU）以秒~十秒计，不可交互
```

**★ 明确结论：0.5B INT4 在带桌面的 1 GB 板子上不可靠，走云端，板子只做转发。**
**本地离线降级 = 纯标准库 RAG（知识库 + 代码总共几十 MB，秒级响应）。**

> 这条结论是任务书明确允许的："不行就纯走云端（板子只做转发）"，但要求**明确决定** —— 已决定。
> 量化脚本 `quantize_llm.py` 会在服务器上回填实测显存/内存数字到 `lora_model/quant/feasibility.md`。

---

## 5. 数据说明（真实来源 + 规模）

- **知识库** `kb/chunks.jsonl`：**536 个 chunks**（平均 ~278 字），按标题层级切分，
  每个 chunk 带 `source`（相对文件路径）与 `title_path`（标题路径）。来源：
  `AI训练交接包(1)/`、`ai_training/docs/00_接口冻结单.md`、`ai_training/src/{common,train}` 的 docstring、`work/prev_cnn/`。
- **LoRA 数据集** `lora_data/{train,val}.jsonl`：**857 条**（grounded 792 + refusal 65），
  train 772 / val 85（固定种子 20261001 分层切出）。sharegpt 风格，每条带 `source` 溯源。
  - grounded 样本全部来自 `FACT_BANK`（人工逐条核对文档事实），用少量自然问法模板扩充。
  - refusal 样本（"今天天气怎么样"等 65 条）用于教模型说"不知道"，抑制幻觉。
- **测试集**（`eval.py` 内置）：**65 条**（53 可答 + 12 应拒答），每条带正确答案要点 + 来源。

> ★ 数据规模与测试集大小均已如实报告；评测数字均为本机实测（见 §2），未运行的（LoRA 训练/量化）已注明。

---

## 6. 团队文件域划分（遵守）

本任务只写了 `src/agent/` 与 `scripts/run_agent.sh`。**未修改** `src/common/`、`src/train/`、
`src/rl/`、`src/serve/`、`docs/00_接口冻结单.md`。
