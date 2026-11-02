# src/rl —— 任务 E：GPU 强化学习训练（示波器自动设置 + 音频 EQ 调优）

> 项目：系统管家小白（Zynq-7020）· AI 训练负责人 · 2026 嵌入式芯片与系统设计竞赛 FPGA 创新设计赛道

本目录实现任务 E 的两个 RL 策略：**目标 ① 示波器自动设置**、**目标 ② 音频 EQ 调优**。

---

## 0. 文件清单

| 文件 | 作用 |
|---|---|
| `scope_env.py` | 示波器自动设置环境（Gym 风格，numpy only） |
| `audio_eq_env.py` | 音频 EQ 调优环境（Gym 风格，numpy only） |
| `ppo.py` | 从零实现的 PPO（PyTorch）+ 硬件同构量化策略网络 |
| `train_scope.py` | 训练示波器策略 + 自动验收（五输入成功率/回报） |
| `train_eq.py` | 训练 EQ 策略 + 平坦度报告（初始 vs 调完） |
| `quantize_policy.py` | int8 量化导出（reference_in/out.bin + weights.bin + model_spec.json）+ 强制自检 |
| `tests/test_envs.py` | 环境单元测试（不依赖 torch / gymnasium） |
| `README.md` | 本文件 |

---

## 1. 为什么选 RL 而不是监督学习

分类（波形识别）是监督学习问题；但 **"调参数"是序列决策问题** —— 调一次、看效果、再调，
这正是 RL 的适用场景。两个任务都满足：

1. **回报可算、稠密**（不是稀疏奖励）；
2. **环境现成**（板子本身就是环境）；
3. **采样快**（示波器一次采集仅 4.3 ms）；
4. **演示肉眼可见**（`render_text()` 把 4096 点采集画成 ASCII 波形 + 当前设置 + 回报分解）。

---

## 2. 目标 ①：示波器自动设置（`scope_env.py`）

### 2.1 MDP 定义

| 项 | 内容 |
|---|---|
| **状态 obs** | 74 维 float32，值域 [-1,1]：64 段波形均值（形状）+ 7 个统计量（直流偏置/展宽/上下包络/峰峰值/占屏/周期数估计）+ 3 个当前设置（触发电平/DEC/垂直增益） |
| **动作 action** | 因子化离散：`(触发电平16档, DEC 16档, 垂直增益5档)`，绝对设置（非增量） |
| **回报 reward** | `w1·占屏(60~80%) + w2·触发电平居中 + w3·显示2~5周期 − w4·丢触发惩罚` |
| **终止** | 三项都接近满分且未丢触发 → 提前成功终止；否则 `max_steps`（默认 10）截断 |

### 2.2 回报公式与权重

```text
t1 = 占屏比例项：梯形，occupy∈[0.6,0.8] 满分，向两侧 [0.4,0.6]/[0.8,1.0] 线性衰减
t2 = 触发电平居中：clip(1 − |trig − mid| / (0.5·span), 0, 1)，mid=(p5+p95)/2
t3 = 周期数项：梯形，K∈[2,5] 满分，向两侧 [0.5,2]/[5,6.5] 线性衰减；K=f·4096/fs
lost = 1（触发电平落在信号 [p5,p95] 之外，丢触发）否则 0

reward = w1·t1 + w2·t2 + w3·t3 − w4·lost
默认权重 (w1,w2,w3,w4) = (1.0, 1.0, 1.0, 0.8)
```

占屏比例 = `(p95−p5)/255`（用 5%/95% 分位数，抗噪/抗削顶）。

### 2.3 信号模型（严格按板卡文档）

- 采集深度 4096 × 8bit；`fs = 20e6 / DEC`；`K = f·4096/fs`；
- 样本 `= clip(round(127.5 + amp·wave(phase)), 0, 255)`，`phase = phase0 + K·n/4096`；
- 波形 0=正弦 1=方波 2=三角 3=锯齿（与 `SRC[2:1]` 一致），4=噪声（见仿真假设 ③）。

### 2.4 动作空间：为什么因子化

笛卡尔积 16×16×5=1280 个动作对 PPO + 小 MLP 而言**每个动作都采样不足**；
因子化后只有 16+16+5=37 个 logits，三个因子独立采样、`log_prob` 相加。
触发电平/DEC/增益本来就近似正交（占屏靠增益、周期靠 DEC、居中靠触发电平），
因子化不仅更好训，也让后续量化成"三个小 argmax 头"，便于板端做成小查找表。

---

## 3. 目标 ②：音频 EQ 调优（`audio_eq_env.py`）

### 3.1 MDP 定义

| 项 | 内容 |
|---|---|
| **状态 obs** | 16 维 float32，值域 [-1,1]：8 个频段的 1/3 倍频程平滑响应(dB) + 8 段当前 EQ 增益(dB) |
| **动作 action** | 因子化离散：8 段 × 各 9 档（−12~+12 dB，步进 3 dB），绝对设置 |
| **回报 reward** | `频响平坦度 − w_gain·增益惩罚` |
| **终止** | RMS 误差 < 1.5 dB 提前成功终止；否则 `max_steps`（默认 8）截断 |

### 3.2 回报公式

```text
平坦度 = −mean( (clip(resp_db − 0, −20, +20) / 20)² )     ∈ [−1, 0]，越大越平
reward = 平坦度 − w_gain · mean( (gain/12)² )              w_gain = 0.02
```

增益惩罚防止"无限加增益"（虽然动作空间已经把增益上限在 ±12 dB，惩罚作为软正则保留）。

### 3.3 频响模型

- 房间/喇叭传递函数（dB）：`低频塌陷(−low_db/(1+(f/low_fc)²)) + 共振峰(1~3 个高斯凸起) + 高频衰减(−hi_db·(f/hi_fc)²/(1+(f/hi_fc)²))`；
- 8 段 EQ：每段在 log 频率域是中心 `fc∈{125,250,500,1k,2k,4k,8k,16k}Hz`、宽 0.5 octave 的高斯凸起；
- 1/3 倍频程平滑：对每个中心频率取 ±1/6 倍频程窗口内的 dB 均值。

### 3.4 动作空间：为什么因子化（而非 9⁸ 笛卡尔积）

8 段 × 9 档的笛卡尔积是 `9⁸ ≈ 4300 万` 个动作，绝对爆炸。因子化后是 8×9=72 个 logits。
8 段增益之间虽然会通过频响串扰轻微耦合，但因子化 + 观测里带"当前响应"就能学到协调。

---

## 4. 算法与超参（`ppo.py`）

**从零实现 PPO**（不依赖 stable-baselines3）：

- **网络**：actor 是浮点 MLP（HardTanh 激活，见 §6）；critic 是浮点 MLP（不部署）。
- **要点**：GAE（λ=0.95）、clip（0.2）、熵正则（ent_coef）、价值损失（vf_coef=0.5）、
  优势归一化、梯度裁剪（0.5）、学习率线性退火、4 个 epoch × 小批量、checkpoint + 超参 json。
- **默认超参**：`lr=3e-4, gamma=0.99, gae_lambda=0.95, clip=0.2, ent_coef=0.01(scope)/0.02(eq),
  vf_coef=0.5, epochs=4, minibatch=256, hidden=[64,64], num_envs=16, num_steps=128`。
- **可复现**：`set_seed()` 固定 torch/numpy/random 种子，环境用独立 `np.random.Generator`；
  超参记录到 `hyperparams.json`，权重保存 `model_final.pt`。

### 训练命令

```bash
# 本地冒烟（CPU 也能跑通）
python src/rl/train_scope.py --smoke
python src/rl/train_eq.py --smoke

# 正式（lab415 GPU）
python src/rl/train_scope.py --total-steps 300000 --out runs/scope_v1
python src/rl/train_eq.py    --total-steps 200000 --out runs/eq_v1
```

---

## 5. 验收指标

| 任务 | 指标 |
|---|---|
| 示波器 | 正弦/方波/三角/锯齿/噪声五种输入各测 N=50 次随机初值，报告成功率与平均回报；目标五种都能稳定显示 |
| 音频 EQ | 调完后频响明显比初始平坦：报告"初始 RMS(dB) → 调完 RMS(dB)"，标称房间 + N 个随机房间 |

`train_scope.py` / `train_eq.py` 训练完**自动跑验收**并把结果写入 `acceptance.json`。

---

## 6. 量化与部署（`quantize_policy.py`）

**必须沿用本项目量化方案（与波形识别模型一致，红线）：**

```text
acc = Σ x_q · w_q                 # int8 × int8 → int32
out = sat((acc × MFQ) >> 16)      # 算术右移=floor，饱和到 [-128,127]
```

- 策略网络是全连接 MLP，量化方式与卷积一致（`acc=Σ x_q·w_q` 用 int32，再 requant）；
- MFQ 是主机校准的整数乘子，**每层可以不同**（硬件里是寄存器）；
- actor 训练时是 **float + HardTanh**（clamp[-1,1]），HardTanh 的硬饱和与 `sat` 逐位同构，
  所以导出用 **PTQ（训练后量化）**：只做"权重 int8 + 逐层 MFQ 校准"，激活/决策几乎零损失
  （导出脚本会报告 float vs 整数策略的 argmax 决策一致率）。

**交付物（与波形模型相同格式，团队红线：必须带 `reference_out.bin`）：**

```text
quantized_policy/
├─ weights.bin          int8 权重（每层 128B 对齐）
├─ model_spec.json      结构 + requant + 内存布局 + 动作解码表
├─ reference_in.bin     N 个 int8 输入（量化后的 obs）
├─ reference_out.bin    N 组 int8 输出（各头 logits 拼接，CPU 整数推理）
└─ README.md
```

**导出后强制自检**：从导出文件读回权重 → 纯 numpy 整数推理（与 HLS 逐位一致，含 int32 回绕模拟）
→ 与 `reference_out.bin` 逐点比对，**必须 100% 一致，不一致非零退出**；另报告 float 前向 vs 整数前向的
argmax 决策一致率（量化损失）+ 逐层溢出检查（`max|acc|·MFQ < 2³¹`）。

```bash
python src/rl/quantize_policy.py --model runs/scope_v1 --out deliverables/scope_policy_quantized
python src/rl/quantize_policy.py --model runs/eq_v1    --out deliverables/eq_policy_quantized
```

板端推理：`i8 = round(clip(obs,−1,1)·127)` → 逐层 `(acc·MFQ)>>16` sat → 各头 argmax → 查 `decode` 表。

---

## 7. ★ 仿真假设与需确认的真机映射（重要，请逐条找对应负责人确认）

### 示波器（找**示波器负责人**确认）

| # | 仿真假设 | 需确认 |
|---|---|---|
| ① | **垂直增益**建模为数字缩放因子 `vgain∈{0.5,0.707,1.0,1.414,2.0}`（等价 V/div 档），作用在采集数据上再 clip。**板子没有真正的模拟垂直增益**，只有 DDS 的 `amp`(0~255) 和 ADC 参考 | 真机上"垂直增益"对应哪个旋钮/寄存器：是 DDS `amp`？是 ADC 参考？还是根本没有（只能软件缩放）？**对不上就按纯仿真档位处理，并明确告知演示时如何呈现** |
| ② | **触发电平不改变采集样本**（Auto 模式总是采满 4096 点），只通过"触发有效性/居中"影响回报 | 真机 Normal 模式丢触发会停更——本仿真用"触发电平在 [p5,p95] 之外→丢触发惩罚"近似。确认演示用 Auto 还是 Normal 模式 |
| ③ | **噪声**波形：`SRC[2:1]` 只有 0~3 四种 DDS 波形，噪声无寄存器对应，建模为高斯噪声源 | 真机"噪声"输入从哪来（外部 ADC/XADC/伪随机源）？触发/居中/丢触发三项在噪声下是否还有意义 |
| ④ | `DEC_LEVELS` 用几何分布的 16 档（1~255），`TRIG_LEVELS` 用均匀 16 档（0~255） | 确认档位划分是否符合真机寄存器语义，是否需要按 1 LSB 连续可调（若连续可调，动作空间可换连续） |

### 音频 EQ（找**主线负责人**确认）

| # | 仿真假设 | 需确认 |
|---|---|---|
| ⑤ | 房间/喇叭传递函数用解析式（低频塌陷 + 1~3 个共振峰 + 高频衰减） | 用真机声学自测（T-2.5）测到的实际频响曲线，替换/校准解析式参数（低频塌陷拐点、共振峰位置等） |
| ⑥ | 8 段 EQ 用"log 频率域高斯凸起"近似每段幅度贡献（段间串扰小） | 真机上 8 段 EQ 由谁实现：软件 IIR / 图示 EQ / ES8388 的音调控制？其 Q 值/斜率/最大增益范围需对齐，否则仿真学到的最优增益不能直接搬真机 |
| ⑦ | "1/3 倍频程平滑"用 ±1/6 倍频程窗口取平均近似 | 对齐真机自测的平滑实现（窗函数、频点网格），确保回报口径一致 |
| ⑧ | 动作 9 档 × 3 dB 步进，绝对设置 | 真机 EQ 增益可调精度（1 dB? 0.5 dB?）与是绝对还是增量，需对齐 |

### 跨任务（找**主线融合负责人**确认）

| # | 仿真假设 | 需确认 |
|---|---|---|
| ⑨ | 输入量化 `i8=round(clip(obs,−1,1)·127)`（round half to even） | 板端实现同一 obs 计算（`_obs()` 函数可直接移植）+ 同一量化，才能与 `reference_in.bin` 对齐；round 方式（half even vs half up）建议统一 |
| ⑩ | 策略网络只做 FC + 饱和（无 ReLU/tanh，硬饱和即非线性），与 HLS `cnn_fc_q` 同构 | 板端若用 PL 加速器，确认能复用 `cnn_fc_q` 通路跑 FC；否则 PS 软件整数推理（小网络 A9 也跑得动） |

---

## 8. 运行测试

```bash
cd ai_training
python -m unittest discover -s src/rl/tests -t .
```

测试**不依赖 torch / gymnasium**（只有 numpy + 标准库），覆盖环境接口、回报公式数值、
termination、随机种子可复现、`render_text()`、可选的 gymnasium 包装（未安装时跳过）。
