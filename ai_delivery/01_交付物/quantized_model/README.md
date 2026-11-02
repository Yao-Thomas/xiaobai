# quantized_model —— 波形识别模型② 交付包

> 项目：系统管家小白（Zynq-7020）· 生成者：AI 训练负责人
> 格式依据：`07_接口约定单.md` 接口 ①（★ 未单方面改动任何必需字段）

## 1. 这是什么

一个 **1×28×28 int8 输入 / 8 类输出** 的小 CNN，与上一轮 PL 侧 CNN 加速器
（`cnn_conv_pool_q` + `cnn_fc_q`）**逐位同构**：把它接上既有 IP 就应当直接跑通。

类别（输出下标顺序）：`sine`, `square`, `triangle`, `sawtooth`, `noise`, `clipping`, `signal_loss`, `duty_abnormal`

## 2. 文件清单

| 文件 | 说明 |
|---|---|
| `weights.bin` | int8 权重，4480 字节（布局见 §4） |
| `model_spec.json` | 模型结构 + requant 参数 + 内存布局 + 精度 |
| `reference_in.bin` | ★ 64 组测试输入，每组 784 字节 int8 |
| `reference_out.bin` | ★ 对应的 64 组输出，每组 8 字节 int8（与硬件逐位一致） |
| `weights.h` | 同一份权重的 C 数组（方便裸机直接 include） |
| `README.md` | 本文件 |

## 3. ★ 怎么验证（板子侧唯一可靠的做法）

```
for k in 0 .. 63:
    把 reference_in.bin[k*784 : (k+1)*784] 拷进加速器输入缓冲（DDR，64B 对齐）
    依次驱动 Conv1 → Conv2 → FC
    读回 8 字节 logits
    与 reference_out.bin[k*8 : (k+1)*8] 逐点比对 → 应 100% 相同
```
期望输出形如上一轮的 `[CNN OK] 8/8 点一致`。

参考样本的类别顺序（方便人工核对）：

```
square, sine, signal_loss, triangle, sawtooth, noise, duty_abnormal, clipping, square, triangle, duty_abnormal, sine, clipping, sawtooth, signal_loss, noise, square, sine, sawtooth, clipping, duty_abnormal, signal_loss, triangle, noise, square, sine, sawtooth, duty_abnormal, signal_loss, triangle, clipping, noise, square, sine, sawtooth, duty_abnormal, signal_loss, clipping, noise, triangle, square, duty_abnormal, sine, sawtooth, clipping, noise, signal_loss, triangle, square, sawtooth, signal_loss, sine, clipping, duty_abnormal, noise, triangle, square, sawtooth, signal_loss, duty_abnormal, clipping, sine, noise, triangle
```

## 4. ★ DDR 内存布局（weights.bin）

```
偏移 0x0000: conv1.weight   shape [8, 1, 3, 3]      72 字节
偏移 0x0080: conv2.weight   shape [16, 8, 3, 3]   1152 字节
偏移 0x0500: fc.weight      shape [8, 400]        3200 字节
文件总长                                         4480 字节
```

| 偏移 | 层 | 形状 | 字节 | 说明 |
|---|---|---|---|---|
| `0x0000` | conv1.weight | [8, 1, 3, 3] | 72 | Conv1 权重 [out_ch=8][in_ch=1][3][3] |
| `0x0080` | conv2.weight | [16, 8, 3, 3] | 1152 | Conv2 权重 [out_ch=16][in_ch=8][3][3] |
| `0x0500` | fc.weight | [8, 400] | 3200 | FC 权重 [out=N][in=400] |

- 每层起始地址 **对齐到 128 字节**；层间与文件尾**补齐到 64 的倍数**（cache line 安全）
- 索引顺序（★ 与 HLS 源码完全一致）：
  - conv: `w[(oc*IN_CH + ic)*KH*KW + ky*KW + kx]`
  - fc  : `w[oc*IN + i]`
- **无偏置**（HLS 不读 bias 数组，网络按 `bias=False` 训练）
- 文件总大小：**4480 字节**

## 5. 各层缓冲区尺寸（DDR）

| 缓冲 | 形状 | 字节 | 建议对齐/补齐 |
|---|---|---|---|
| input_img | - | 784 | 832 |
| conv1_out_f1 | [8, 13, 13] | 1352 | 1408 |
| conv2_out_f2 | [16, 5, 5] | 400 | 448 |
| logits | [8] | 8 | 64 |

> ★ 上一轮的坑：输出缓冲**最后一条不完整 cache line 未失效**会让板端结果尾部全 0。
> 所有缓冲请 64 字节对齐 + 长度补齐到 64 的倍数（上面已给出 padded 值）。

## 6. requant（★ 沿用上一轮方案，硬件零改动）

```
out = relu/sat((acc * MFQ) >> 16)      # conv: relu+sat 到 [0,127]
                                        # fc  : sat 到 [-128,127]（无 ReLU）
```
| 层 | MFQ |
|---|---|
| conv1 | 201 |
| conv2 | 371 |
| fc | 1390 |

**★ 为什么要说明这一点：**
`MFQ` 在 HLS 里是 `s_axilite` 寄存器（`cnn_conv_pool_q(..., int MFQ)`），
**每次调用独立传入，不是硬件常量**。上一轮的 `MFQ=119` 是那个 MNIST 模型的
主机校准值；本模型是另一个网络、另一种输入分布，必须重新校准。
方案本身（`(acc×MFQ)>>16` + 主机校准）完全沿用，PL 侧一行都不用改。

**兼容回退**：若板端只支持「整个网络用一个 MFQ」，请用同一目录旁的
`quantized_model_uniform_mfq/`，那里 MFQ 统一为 **119**（测试集准确率 0.5540，原逐层版 0.9590）。

## 7. 输入预处理（capture → 28×28）

示波器 4096 个 8 位样本 → 28×28 uint8 图像 → `int8 = u8 - 128`。

**本模型使用的输入表示：`wdens`（时间×幅度密度图）**
```
 28 列 = 时间（把 4096 个采样点均分成 28 段，每段 146 点）
 28 行 = 幅度（8 位码值 0~255 均分；行 0 = 顶部 = 高电平）
 每个格子的值 = 该列内落在该幅度档的采样点【个数】
   → 除以该列总点数得到列内密度 → 开平方（方差稳定化）
   → 按【本样本自身最大值】归一化到 0~255
```
为什么不用 STFT：STFT 要分开谐波需要「一个窗内至少 2 个周期」，
而示波器为显示 2~5 个周期时缓冲区内只有 K=2~5 个周期 ⇒ 谐波完全糊在一起。
密度图在少周期时直接给出波形形状，多周期时退化为各列的幅度分布
（正弦=反正弦分布 / 三角=均匀 / 方波=双尖峰 / 噪声=高斯），两个工况下都有判别力。
**实测对比见 `docs/01_输入表示选型.md`。**

**参考实现：`src/common/preprocess.py`（含 numpy 与纯 Python 两条路径，逐点一致）。**
板端若要用，直接拷这个文件即可（无第三方依赖）。

## 8. 精度

| 项 | 值 |
|---|---|
| 测试集准确率（整数前向，与硬件一致） | **0.9590** |
| 浮点基线（量化前） | 0.9635 |
| 量化损失 | 0.0045（目标 < 0.02） |
| 测试集规模 | 2000 |

## 9. 注意事项

- 输入必须是 **int8**，值为 `uint8-128`；不要送原始 0~255。
- 每层权重起始地址必须按 §4 的表；不要重新排列层顺序。
- 中间特征图 f1/f2 直接由加速器写 DDR 并被下一层读回，
  **CPU 侧不要对它们做 flush**（上一轮的坑：会把旧值刷回去覆盖加速器结果）。
- 所有缓冲区按 §5 的 padded 尺寸分配。
