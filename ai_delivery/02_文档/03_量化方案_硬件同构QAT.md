# 03 · 任务 F：量化方案 —— 硬件同构 QAT

> 验收标准（任务书）：**量化后精度下降 < 2%；导出格式能被板端加载**
> 实测：**量化损失 0.0045（0.45%）**，导出格式自检 **512/512 点一致**。✅

---

## 1. 为什么要"硬件同构"

上一轮的交接包里有一条教训：

> **Non-true requantization**：上一轮 M4b-4 用了粗略 `>>8`，导致 argmax 落在错误类别。
> **必须用真实 requantization**（`MFQ` 校准）

但"用真实 requantization"还有一个更强的要求容易被忽略：

> **训练时用的整数前向，必须与 PL 里 HLS 写的那段循环逐位一致。**
> 否则训练出来的模型是"另一个网络"，导出的 `reference_out.bin` 与板子实测对不上，
> 集成时会去改**压根没问题**的 RTL。

所以本项目把量化做成了"**硬件同构 QAT**"：
训练、评估、导出**全部走同一条整数通路**，并且用单测锁死它与 numpy 硬件复刻的逐点一致性。

---

## 2. 硬件的确切语义（照抄 HLS 源码）

`源码/hls/cnn_conv_pool_q.cpp`：
```cpp
acc = Σ_ic Σ_ky Σ_kx  img[...] * w[...]        // int8 × int8 → ap_int<32>
q   = (acc * MFQ) >> 16                         // ★ 算术右移 = floor
q   = clamp(q, 0, 127)                          // ReLU + 饱和
out = max over 2×2 window                       // max-pool 与卷积融合
```
`源码/hls/cnn_fc_q.cpp`：
```cpp
acc = Σ_i x[i]*w[oc*IN+i]                      // ap_int<32>
q   = (acc * MFQ) >> 16 ;  q = clamp(q, -128, 127)   // FC 无 ReLU
```
- 权重索引：conv `w[(oc*IN_CH+ic)*KH*KW + ky*KW + kx]`；fc `w[oc*IN + i]`
- **无偏置**（HLS 不读 bias 数组）⇒ 网络必须 `bias=False`
- `acc*MFQ` 在 `ap_int<32>` 里算 ⇒ **溢出会回绕**

---

## 3. ★★ 一个只有靠逐点自检才能抓到的致命 bug

`src/common/qmodel.py::_exact_requant` 第一版是这样写的：

```python
prod = acc.double() * float(int(mfq))
q = _ste_floor(prod) * (1.0 / float(1 << SHIFT))    # ← 错！
```

它算的是 **`floor(acc·MFQ) / 2¹⁶`**，而硬件算的是 **`floor(acc·MFQ / 2¹⁶)`**。
两者**根本不相等**：`floor(k)/65536` 一般不是整数，于是 torch 侧的激活值全是**小数**，
而 numpy 硬件复刻是整数。

**为什么特别难发现**：把小数 `astype(int64)` 截断后，**多数值看起来是对的**
（104.7 → 104），只有本来就很接近整数边界的值才露馅。
当时的表现是：`test_matches_with_random_mfq` 里 9 个 logits 有 3 个差 1~3。

**后果如果没抓到**：训练出来的模型与板子实测不一致 → 集成时被判"硬件输出错" →
去查 RTL / 查 cache / 查地址段 —— **全是白干**。

**修复**：
```python
prod = acc.double() * float(int(mfq)) * (1.0 / float(1 << SHIFT))
return _ste_floor(prod).float()
```
（`acc·MFQ ≤ 1e10 < 2⁵³`，float64 内乘法精确；除以 2¹⁶ 是 2 的幂，也精确 ⇒ floor 结果与整数运算完全一致。）

**抓出它的正是 `tests/test_qmodel.py` 的逐点比对断言**（13 项）。这条经验已经写进
`docs/07_交接与验收报告.md` 的第 1 条。

---

## 4. 逐层 MFQ：为什么不能照抄 119

`(acc·MFQ)>>16` 要"用满 int8 输出范围而不饱和"，需要：

```
MFQ ≈ 127 · 2¹⁶ / max|acc|
```

而 `max|acc|` 取决于该层累加次数：Conv1 只有 9 次，FC 有 400 次 —— **差 40 倍以上**。
一个统一 MFQ 必然让某些层的权重被压到只剩 1~2 个量化级。

**实测（本模型）**：

| 版本 | 测试集准确率 |
|---|---|
| **逐层 MFQ（201 / 371 / 1390）** | **0.9590** |
| 统一 MFQ = 119 | 0.5540 |

⇒ 逐层是必须的。而 `MFQ` 在 HLS 里本来就是 `s_axilite` 寄存器，
**每次调用可传不同值 ⇒ 硬件零改动**。

---

## 5. ★ 激活标定：分位数而不是 max

requant 是 **floor**，所以 `acc·MFQ/2¹⁶ < 1` 的值会被压成 0 —— 存在**死区**。
按 `max` 标定时死区 = `max|acc|/127`；而卷积输出分布**重尾**
（少数位置很大、绝大多数很小），按 max 标定会让大量通道"死掉"：

> 实测（按 max 标定）：**conv2 输出 88.8% 被压成 0**，网络等于空转。

改用 **99.9 分位数**标定后死区显著缩小（代价是前 0.1% 饱和），
这是标准做法（TensorRT 的 percentile 校准）。

**标定公式**（已在代码注释里推导）：
```
s_y_L = s_x_L · s_w_L · pct_L / 127      ⇒   MFQ_L = 127·2¹⁶ / pct_L
```

`s_w` 用标准对称量化初始化：`s_w = max|W_L| / 127`。

---

## 6. ★ 溢出安全

```
约束： max|acc| × MFQ < 2³¹
```

按上面的标定公式，`max|acc|·MFQ = 127·2¹⁶ = 8.3e6 ≪ 2³¹` —— **天然安全**。
但代码仍然**逐层实测**并写入报告：

| 层 | max\|acc\| | MFQ | acc×MFQ | int32 余量 |
|---|---|---|---|---|
| conv1 | 54518 | 201 | 1.1e7 | **196×** |
| conv2 | 33563 | 371 | 1.2e7 | **172×** |
| fc | 13437 | 1390 | 1.9e7 | **115×** |

并且 `reference_infer_arrays()` 里**逐位模拟了 int32 回绕**（`wrap_int32`），
所以哪怕将来真溢出，`reference_out.bin` 与真硬件**仍然一致**。

---

## 7. 训练流程（三阶段）

```
P1 浮点预训练   70 epoch，同一尺度（x = u8-128），bias=False，focal γ=2.0
                → 结束时记录【纯浮点基线】（这是"量化损失"的分母）
P2 量化校准     s_w = max|W|/127；s_y 用 99.9 分位标定（迭代 3 次收敛）
P3 硬件同构QAT  55 epoch，前向 = 整数通路（floor + 饱和），STE 传梯度
                权重与 6 个量化步长都参与优化
导出            整数权重 → weights.bin；逐层 MFQ → model_spec.json
                强制自检：读回文件 → 整数推理 → 与 reference_out 逐点比对
```

**★ "量化损失"的分母必须是 P1 结束时的纯浮点准确率。**
第一版误用了"QAT 权重的浮点视图"，得出"量化损失 = 0"甚至为负的假结论
（QAT 权重是为整数前向优化的，其浮点视图本来就更差）。已修。

---

## 8. 验证证据一览

| 验证 | 方式 | 结果 |
|---|---|---|
| torch 整数前向 == numpy 硬件复刻 | `tests/test_qmodel.py`（13 项，含随机 MFQ、极端输入、批/单样本一致、int32 回绕、索引顺序） | **13/13 通过** |
| 真实模型上两者一致 | 训练脚本对 2000 条测试样本跑两遍 | **0.9590 == 0.9590，逐点一致 ✅** |
| 导出文件自洽 | `export_quantized.py` 末尾强制自检（读回 `weights.bin` + `reference_in.bin` → 与 `reference_out.bin` 逐点比对，不一致就非零退出） | **512/512 点一致；argmax 自洽 64/64** |
| 权重在 int8 范围内 | 单测断言 | ✅ |
| 无 int32 溢出 | 逐层实测 + 余量报告 | ✅ 余量 115×~196× |

---

## 9. 关键文件

| 文件 | 作用 |
|---|---|
| `src/common/qmodel.py` | 硬件同构量化模型 + numpy 硬件复刻 + 诊断 |
| `src/train/train_waveform.py` | 三阶段训练（P1/P2/P3）+ 逐类召回 + 混淆矩阵 |
| `src/train/export_quantized.py` | 导出 `quantized_model/` + **强制自检** |
| `tests/test_qmodel.py` | ★ 13 项逐位一致性单测 |
