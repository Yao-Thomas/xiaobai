# FPGA2026 · AMD赛道 项目交接说明（总览 + 索引）

> 项目：全国大学生嵌入式芯片与系统设计竞赛'2026 · FPGA创新设计赛道 · **AMD** · **自主选题赛道**
> 目标：在 Zynq-7020 上跑通 **CPU(PS) – FPGA(PL) – NPU(加速器)** 链路，为 AI 加速打基础。
> 板卡：**正点原子 领航者 ZYNQ 开发板 7010/7020 (V2)**，核心板 V2.5，底板 V3.9（音频 ES8388）
> 器件：**XC7Z020-CLG400-1**　工具：**Vivado/SDK/Vitis HLS 2018.3**（注意竞赛要求 2025.2/2026.1）

---

## 一句话现状
**M1-M4a 全部在真机上跑通**——LED、SD启动+串口、CPU→AXI→加速器、真 3×3 卷积。**下一步是 M4b（CNN/MNIST 推理）。**

## 交接文档索引
| 文档 | 内容 |
|---|---|
| `01_阶段任务与里程碑.md` | 各里程碑状态、成果、预期输出、下一步 M4b 方案 |
| `02_阶段经验与踩坑合集.md` | 全部踩过的坑、关键参数、命令（很重要，别重踩） |
| `03_板卡配置.md` | 正点原子领航者 V3.9 官方 PS 配置 / 引脚 / 启动 |
| `04_构建与复现指南.md` | 一键复现：环境/工程/位流/BOOT.BIN 全流程 |

## 代码 & 产物位置（构建目录必须纯 ASCII）
> 中文路径会让 Xilinx 工具报错，**可构建工程在纯 ASCII 路径**。
- **可构建工程**：`D:\FPGA2026_PRJ\zynq_ai_accel\`
  - `src\hls\` 卷积核 HLS、`src\rtl\` AXI 加速器（conv_accel_axi_lite / conv2d_accel / led_blink）、
    `src\ps_sw*` PS 软件、`sim\` 仿真、`build\` 全部 TCL 脚本、`board\` 产物（bit / hdf / BOOT.BIN）
- **文献/文档归档**：`D:\总文件夹\FPGA2026\zynq_ai_accel\docs\`（ROADMAP / BOARD_CONFIG / INTERFACE / BRINGUP）

## 下一步（M4b）
升级为**真 CNN 推理（MNIST 数字分类）**：2 层卷积+池化+全连接，加 DMA/AXI-Stream 搬运真实图像+权重，PS 喂手写数字图，加速器跑推理，串口打印识别类别。详见 `01_…` 的 M4b 方案。

## 关键提醒（拿走就能用）
- 用 `launch_runs` 构建（勿直接 `synth_design`）。
- 自定义 IP 需先打包成 IP（`ipx::package_project`），BD 里 `-type ip -vlnv`。
- AXI 互联 **NUM_MI=2**（单从机 NUM_MI=1 会写卡死）。
- 启动：SD 卡 FAT32 + `BOOT.BIN`，boot=SD，P5=PS 串口，串口 115200-8N1。
