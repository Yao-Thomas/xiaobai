# 05 · M4b 方案：真 CNN 推理（MNIST 手写数字分类）

> 目标：在板子上真正跑一个神经网络，PS 喂一张 28×28 手写数字图，PL 加速器做 CNN 推理，串口打印「识别为 X」。
> 思想：基于已跑通的 M3/M4a 链路（CPU↔AXI↔加速器）往上盖楼。

## 1. 网络选型（推荐：LeNet-5 级，够小、可上 Zynq-7020）
```
输入 28×28×1
Conv1: 3×3, 1→8 通道, ReLU     -> 26×26×8
Pool1: 2×2 max                  -> 13×13×8
Conv2: 3×3, 8→16 通道, ReLU     -> 11×11×16
Pool2: 2×2 max                  -> 5×5×16   (=400)
FC:   400 → 10                  -> 10 logits
argmax -> 0-9
```
- 参数量很小（几百~几千），Zynq-7020 的 LUT/DSP/BRAM 能轻松放下。
- 用 PyTorch 训练（MNIST 98%+），导出 **int8 量化权重**为数组文件。

## 2. 数据通路：加速器读 DDR（关键，比现在寄存器方式强）
- 现在 M4a 卷积核只吃 `64` 个寄存器（小图）。CNN 要 28×28 图 + 多层权重，必须能读大块数据。
- 方案：**加速器用 `m_axi`（AXI 主控）直读 DDR**，PS 只需把「输入图基址、权重基址、层参数」写进控制寄存器，加速器自己搬运并计算。
  - 加一层**参数化卷积/池化/全连接**引擎 + 一个**控制 FSM**（按层描述符依次执行）。
- 或者：**DMA + AXI-Stream**（数据流式进加速器）。二者可选，`m_axi` 更直接。

## 3. 分步实现（每步可用仿真+板上验证）
| 子步 | 内容 | 验证 |
|---|---|---|
| **M4b-1** | 把卷积加速器改为**核心从 DDR 读图/写结果**（m_axi 或带 DMA），不再只吃寄存器 | PS 把 28×28 图写进 DDR，加速器读入并做一层卷积，结果写回 DDR，板上比对 |
| **M4b-2** | 参数化**卷积层 + ReLU + max-pool**（输入/输出通道、核尺寸、stride/padding） | 单层 8 通道卷积+池化，结果正确 |
| **M4b-3** | **全连接层**（矩阵×向量） | FC 结果正确 |
| **M4b-4** | **按层描述符串起多层**（Conv→Pool→Conv→Pool→FC） | 端到端推理出 logits |
| **M4b-5** | **MNIST 权重 + 测试图**：PyTorch 训练/导权重，PS 喂图，板上分类 | 串口打印「识别为 X」，和 CPU 版比对 |

> 每步都像 M1-M4a 一样：仿真对了 → 打包 IP → 建 BD（NUM_MI=2！）→ 综合 → BOOT.BIN → 你上板看结果。

### 当前进度（M4b-1 ✅ 板上实测通过）
- **板上已实测**：`[CNN OK] 676/676 点一致`，HW 输出与 C 软件参考逐点相同（row12=20 -11 -12 -26 21 21 39）。

### M4b-2 进度（已构建，待板上验证）
- **`src/hls/cnn_conv1_pool.cpp`**：单核 Conv(1→8,3×3)+ReLU+2×2 MaxPool，m_axi 走 DDR，输出 13×13×8。
- 复用 M4b-1 的打包/BD/地址套路；上板件 `board/BOOT_CNN2.BIN`。
- 期望串口：`[CNN OK] 1352/1352 点一致`，且
  `ch0 row6: ...20 0 29 39...`、`ch1 row6: ...8 0 43 5...`、`ch7 row6: ...28 23 11...`。

### M4b-3 进度（✅ 板上实测通过）
- **`src/hls/cnn_conv_pool.cpp`**：**通用** Conv+ReLU+MaxPool（支持任意输入/输出通道，带 ic 循环），可同时做 Conv1 和 Conv2。
- 本步用 **Conv2(8→16)** 验证多输入通道：CPU 先算 Conv1+pool 得 fb1(13×13×8)，再让加速器对它做 Conv2+pool→fb2(5×5×16)。
- 上板件 `board/BOOT_CNN3B.BIN`（常量维度版 `cnn_conv_pool2`）。
- 关键排障：板端 `[CNN FAIL]`(ch15 尾段全 0) 根因是 **CPU 缓存一致性**（输出缓冲最后一条不完整 cache line 未失效），非硬件逻辑；csim 证明 C 模型正确。
- 通过标准：`[CNN OK] 400/400 点一致`，ch8 row2=21 28 42 39 39、ch15 row2=20 4 9 0 0。

### M4b-4 进度（✅ 板上实测通过）
- **`src/hls/cnn_fc.cpp`**：全连接层 FC(400→10)，m_axi 走 DDR，`out=Σx·w >>8`。
- 上板件 `board/BOOT_FC.BIN`。通过标准：`[CNN OK] 10/10 点一致`，logits `65 -79 -19 1 96 -56 -100 7 -101 19`。
- **注意**：此步用粗略 `>>8`，argmax 落在 4（非真实 label 7）——因为非真实 requantization；分类正确性属 M4b-5。

### M4b-5 进度（✅ 板上实测通过 —— A 主线完成）
- **`src/hls/cnn_conv_pool_q.cpp`**（通用 Conv+ReLU+Pool，可配 Conv1/Conv2）+ **`src/hls/cnn_fc_q.cpp`**（FC）。
- 两个 IP 同建一 BD：cpq`0x43C00000`、fcq`0x43C10000`，PS 端到端调度 Conv1→Conv2→FC，中间特征图在 DDR 传。
- **真实 requantization**：每层 `out=relu/sat((acc×MFQ)>>16)`，`MFQ=119 统一(主机校准)`；不用偏置数组。
- 上板件 `board/BOOT_M4B5.BIN`。通过标准：`argmax=7`，hw logits==ref `-38 -89 9 5 -119 -49 -128 58 -42 -9`。
- 排障：① 权重须先 flush 到 DDR；② **加速器输出接下一层输入时不要在 CPU 侧 flush**（会覆盖回旧值）。

### A 主线（完成）
- M4b-1..5 全部板上验证通过：数据通路(m_axi/DDR) → Conv1+Pool → Conv2(多通道)+Pool → FC → 端到端 MNIST 识别数字 7。
- **已做**：`src/hls/cnn_conv.cpp`（单通道 3×3 卷积，`m_axi` + `s_axilite`），HLS 综合出 RTL。
  - 关键坑（重复踩）：HLS `export_design` 打到 `core_revision`（自动修订号 > int32）报
    `bad lexical cast`。规避：用 `build/package_ip_cnn.tcl` 对 **HLS 生成 RTL** 跑
    `ipx::package_project`（与 M4a 的自定义 RTL 打包同一招）。
  - HLS 按 10ns(100MHz) 综合；BD 里把 IP 的 `m_axi_gmem`/`s_axi_AXILiteS` 接口
    `FREQ_HZ` 统一到 **50MHz**（FCLK_CLK0 默认），避免互联 FREQ_HZ 校验失败。
- **BD**（`build/run_bd_cnn.tcl`）：PS7 启用 `S_AXI_HP0`；GP0 从机=2（AXI GPIO + cnn s_axilite，
  沿用 `NUM_MI=2` 铁律）；cnn 的 `m_axi_gmem` 经 `axi_hp(1SI:1MI)` 接 `S_AXI_HP0` 直读/写 DDR。
  - 地址：cnn `0x43C00000`，GPIO `0x41200000`，HP0 DDR 段 `0x00000000 [1G]`。
- **软件**（`src/ps_sw_cnn/main_cnn.c`）：把 TEST_IMG(${测试图label=7}) + W1 第0通道放 DDR →
  缓存 `Xil_DCacheFlushRange` → 配寄存器(基址/IH/IW/KH/KW) → `ap_start=1` → 轮询 `ap_done` →
  `Xil_DCacheInvalidateRange` 读回 → 与 C 软件参考逐点比对（676 点）。
  - 输出应显示 `[CNN OK] 676/676 点一致`，且 `out row12` 出现非零（参考 20 -11 -12 -26 21 21 39）。
- **上板件**：`board/BOOT_CNN.BIN`（boot_cnn.bif 组成 fsbl+chain_cnn.bit+chain_app.elf）。

## 4. 素材准备（需要你/我下载或训练）
- **MNIST 测试图**（28×28 灰度图，一张手写数字）。
- **训练好的权重**（PyTorch 训练 MNIST，导出 int8 + 量化，生成 C 数组 / 文件）。

## 5. 交付物（M4b 完成后）
- 一个真正的 **CNN 加速器 IP**（参数化、可复用、可裁剪）。
- 端到端 **MNIST 识别 demo**（板上跑，准确率可测）。
- 复现脚本 + 训练/导出权重脚本 + 设计文档。

## 6. 工作量 / 风险
- 工作量：这是目前最大的一步，核心是「数据通路（DDR/AXI）+ 参数化算子 + 层调度」。
- 风险：数据流和时序（尤其 m_axi 的地址/长度）较繁琐；故分 5 个子步逐个闭环，出问题好定位。
- 优点：链路底座（M1-M4a）已全通，是在已验证的结构上加内容，可控。

## 7. 版本提醒
- 用 2018.3 先做通；竞赛要求 2025.2/2026.1，升级后本方案的算子/数据通路概念可平移。
