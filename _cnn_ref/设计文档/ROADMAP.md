# Zynq AI Acceleration —— 技术路线与里程碑

> 项目：全国大学生嵌入式芯片与系统设计竞赛'2026 · FPGA 创新设计赛道 · **AMD**
> 赛道：**自主选题赛道**（参赛范围：可选 Zynq-7000 / 7 系列器件）
> 板卡：**正点原子 ZYNQ7020**（XC7Z020, Zynq-7000）
> 目标：跑通 **CPU(PS) – FPGA(PL) – NPU(加速器)** 链路，为 AI 加速奠定基础。

---

## 1. 目标与命题

在 Zynq-7020 上，本设计把**神经网络计算核心**放到 FPGA 逻辑（PL）里实现，
把**主机控制**放在 ARM Cortex-A9（PS）里，两者通过 **AXI 总线**互联，构成：

```
   ┌───────────── PS (ARM Cortex-A9, 主机) ─────────────┐
   │  Linux / 裸机    控制、调度、数据搬移、任务管理          │
   └──────────┬──────────────────────────────────────────┘
              │ AXI (AXI4-Lite 配置/状态 · AXI4 数据搬运)
   ┌──────────▼──────────────────────────────────────────┐
   │             PL (FPGA 逻辑)                             │
   │   ┌───────────────────────────────────────┐          │
   │   │  NPU / 加速器 (CNN/GEMM 计算核心)         │          │
   │   │  RTL 或 HLS 实现，AXI 从机             │          │
   │   └───────────────────────────────────────┘          │
   └─────────────────────────────────────────────────────┘
```

> 注意：**XC7Z020 芯片没有硬件 NPU 块**。这里的 “NPU” 是本设计实现于 PL 的
> **自定义神经网络加速器**（Vitis AI DPU 或自研 RTL/HLS 计算核）。

---

## 2. 关键决策（已确认）

| 决策项 | 结论 | 理由 |
|---|---|---|
| 参赛赛道 | 自主选题赛道 | 直接用到手里的 ZYNQ7020，可做板级 AI 加速 |
| 工具版本（当前） | Vivado / SDK / Vitis HLS **2018.3** | ALIENTEK 配套，已验证可用；先用它跑通链路 |
| 工具版本（竞赛投递） | **2025.2 或 2026.1**（官方推荐） | 竞赛前升级；旧工程需迁移（见 §5） |
| Ryzen AI PC | 暂不定 | 自主选题不需要，不阻塞 |
| NPU 实现方式 | **自研 RTL/HLS 加速器（首选）** | 2018.3 无法跑 Vitis AI 官方 DPU；自研可控、可复现 |

---

## 3. 里程碑（板子到货前 = 纯主机可验证）

> ✅ = 已完成并可验证；⬜ = 待办

### M1 环境就绪（✅）
- Vivado / SDK / Vitis HLS 2018.3 全部启动正常，license（至 2037）生效。
- 一键环境脚本：`env/setup-env.ps1`。
- 关键修正：**路径必须为纯 ASCII**（详见 §7）。

### M2 跑通 HLS（✅）
- `conv2d`（3×3 卷积核）C++ → Vitis HLS 综合成 RTL（Verilog/VHDL/SystemC），
  目标 `xc7z020clg400-1`，时钟 10ns。C 仿真与 IP 打包另有注意事项（见 §9）。

### M3 跑通硬件链路（✅ 板上实测）
- Block Design：Zynq PS + AXI Interconnect + AXI GPIO + 自定义加速器(`conv_accel_axi_lite`)
  已建并校验通过，地址已分配（加速器 `0x43C00000`，GPIO `0x41200000`）。
- `launch_runs` 流程成功综合 + 实现 + 生成 bitstream（`board/chain.bit`），时序收敛 WNS 为正。
- **板上已实测通过**：SD 启动 → UART0 打印 `[CHAIN OK] RESULT=87`（CPU→AXI→PL 乘法加）。

### M4 PS 侧软件（✅ 板上实测）
- `src/ps_sw/main.c`（M3 链路）、`src/ps_sw_conv2d/main_conv2d.c`（M4a 卷积）均已上板验证。
- BSP 用 `.hdf`（`write_sysdef` 生成，WebPACK 下 `write_hw_platform` 不可用，见 §9）。

### M4a 真 3x3 卷积（✅ 板上实测）
- `src/rtl/conv2d_accel.v` 作为 AXI4-Lite 从机（4×4→2×2），板级输出 `[CONV2D OK] 45 54 / 81 90`。

### M4b-1 CNN m_axi 数据通路（✅ 板上实测）
- 用 **Vitis HLS（`cnn_conv.cpp`）+ m_axi** 生成单通道 3×3 卷积核，读/写走 DDR（S_AXI_HP0）。
- 规避 HLS `core_revision` 打包 bug：用 `ipx::package_project` 打包 HLS 生成 RTL。
- **板上已实测通过**：`[CNN OK] 676/676 点一致`（HW vs C 软件参考），`row12` 输出 20 -11 -12 -26 21 21 39。
- 内存布局：img/w/out 放 DDR，cache 用 `Xil_DCacheFlushRange` / `Xil_DCacheInvalidateRange` 保证一致性。

### M5 仿真验证（✅）
- `sim/tb_conv_accel.v`（xsim）验证 AXI 加速器：A=6,B=7,C=5,D=9 → RESULT=87，
  STATUS=valid，`[TB] ALL PASS`。

### M6 真 CNN（✅ 完成）
- 复用 m_axi 数据通路，完整走通：
  【M4b-2】Conv1(1→8)+ReLU+Pool（✅ 板上）；
  【M4b-3】通用 Conv+Pool，用 Conv2(8→16) 验证多输入通道（✅ 板上，cache-line 坑已解决）；
  【M4b-4】全连接层 FC(400→10)（✅ 板上）；
  【M4b-5】端到端：PS 依次驱动 Conv1→Conv2→FC + 真实 requantization(`(acc×MFQ)>>16`)，串口识别数字 **7**（✅ 板上）。
- **A 主线完成**：板上真正跑通 CPU(PS)–AXI–加速器–DDR 的 CNN 推理，识别手写数字 7。

---

## 4. 当前阻塞与前置条件

- **板子未到**：M3 的 bitstream 生成、M4 的 `.elf`、M5 上板实测都要等板子。
  但 M2/M3 的综合实现、M4 的交叉编译、M5 的仿真都**可在主机完成**。
- **AXI/PS 配置参数**：不同 ZYNQ7020 板（领航者/达芬奇等）DDR 型号、时钟、
  外设映射可能不同。上板时需按 **具体板卡的原理图** 修正 PS 配置。

---

## 5. 版本迁移路径（2018.3 → 2025.2/2026.1）

竞赛主工具按官方推荐应为 **Vivado / Vitis 2025.2 或 2026.1**。升级影响：

1. **SDK 改名**：2018.3 用 `Xilinx SDK`（`xsdk`）；2020.1+ 统一为 **Vitis**。
   裸机/嵌入式 app 流程与界面变化较大，需重做 M4 的构建方式。
2. **HLS 改名**：`Vivado HLS` → `Vitis HLS`，C++ 语法/SIMD 库基本兼容，需微调指令。
3. **Block Design 不兼容**：.xpr 工程不可跨大版本迁移，需用 TCL 脚本重建。
   ➡️ 这正是我们坚持用 **TCL / 非工程模式** 的原因：升级时跑一遍脚本即可重建成
   2025.2 工程，可复现性最好。
4. **Vitis AI（官方 DPU/NPU IP）**：需 2020.1+ 且对 Zynq-7000(armv7) 支持弱。
   ➡️ 本方案走**自研加速器**，不受限制；升级后如需官方 DPU 再评估。

---

## 6. 可复现性要求（竞赛硬性要求）

- 目录/文件名一律**纯英文小写+数字+下划线/连字符**（本项目已照做）。
- 所有构建用 **TCL / 脚本**，跑一遍就能重建工程，见 `build/` 与 `src/block_design/`。

---

## 7. 环境注意事项（重要）

- **可构建工程的路径必须是纯 ASCII**。Xilinx 工具（Vivado/SDK/HLS）在 Windows 上会因
  中文/非 ASCII 路径而报错（实测：`D:\总文件夹\...` 截坏了项目名）。
  因此**可构建工程**放在纯 ASCII 根目录：
  **`D:\FPGA2026_PRJ\zynq_ai_accel`**（不含中文，脚本/源码/构建结果都放这里）。
- 本仓库（`D:\总文件夹\FPGA2026\zynq_ai_accel`）作为**文档/归档**，记录路线、报告等；
  可构建工程以 ASCII 影目录为准。两者保持同步。
- 这正好与竞赛“目录/文件名纯英文”的要求一致。

## 8. 目录结构（对应官方 3.3.5.4）

```
zynq_ai_accel/
├── README.md
├── src/
│   ├── hls/            # 加速器 C++ + HLS 脚本
│   ├── rtl/            # RTL 源码 / AXI 包装
│   ├── block_design/   # Block Design TCL
│   └── ps_sw/          # PS 侧裸机软件
├── sim/                # testbench + 仿真结果
├── build/              # 构建脚本 + 综合/实现报告
├── board/              # 上板工程、BOOT.BIN、实测输出
├── data/               # 测试数据与参考结果
├── skill/              # 技能包（加分项）
├── report/             # 设计报告 + 大模型协作记录
└── docs/               # 路线/架构/接口文档（本文件所在）

---

## 9. 已踩过的坑与解决（重要经验）

| # | 问题 | 现象 | 解决 |
|---|---|---|---|
| 1 | **路径含中文** | HLS 报 `name contains illegal character` | 使用**纯 ASCII** 构建目录（`D:\FPGA2026_PRJ\zynq_ai_accel`） |
| 2 | **open_project 带盘符** | HLS `open_project` 报 `illegal ':'/'` | 先 `cd` 到目录，再用**纯工程名** `open_project -reset name` |
| 3 | **HLS 少 solution** | `csynth_design` 报 `You must open a solution first` | 加 `open_solution -reset` + `set_part` + `create_clock` |
| 4 | **HLS export 参数** | `export_design` 报 `Unknown option '-output'` | 2018.3 无 `-output`；用 `-ipname` 命名 |
| 5 | **HLS csim** | `can't read "::AESL_CSIM::gLogfl"` | 该 build 的 csim 已知问题；改用 CSYNTH + xsim 手工验证 |
| 6 | **HLS IP 打包** | `bad lexical cast ... core_revision` | locale bug；暂缓，改用自定义 RTL IP（见 §3 M3/M6） |
| 7 | **自定义模块进 BD** | `design_1_<cell>_0_0 not found` | 无头 TCL 下 `-type module` 不被综合；改用**打包成 IP** 再 `-type ip -vlnv` |
| 8 | **headless OOC 综合** | Xilinx IP 也报 `not found` | 用 `launch_runs -jobs N synth_1`（自动触发 IP OOC），勿直接 `synth_design` |
| 9 | **write_hw_platform** | `invalid command name`（WebPACK 授权） | 用 `write_sysdef` 生成 `.sysdef` 复制为 `.hdf`；xsct `createhw -hwspec <.hwh>` 可直接用 `.hwh` |
| 10 | **单从机 AXI 互联** | 自定义 IP 作唯一从机（NUM_MI=1）时真机 AXI 写卡死 | 改用 **NUM_MI=2**（多加一个 AXI GPIO），与已验证跑通的结构一致 |
| 11 | **位宽截断** | `3'd8`/`6'h40` 等超出位宽被截断成别的值（如 `3'd8`→0） | 常量位宽要够：用 `4'd8`、`7'h40`；地址/寄存器映射确保在地址位宽内 |
| 12 | **HLS IP 频率不匹配** | HLS 按 10ns(100MHz) 综合，而 FCLK_CLK0 默认 50MHz → BD 校验报 `FREQ_HZ does not match` | 在 BD 里把 IP 的 `m_axi_*`/`s_axi_*` 接口 `FREQ_HZ` `set_property` 统一到 50MHz（跑得慢更稳） |
| 13 | **xil_printf 打印中文** | 串口出现 `鏁版嵁閫氳矾` 等乱码 | `xil_printf` 仅支持 ASCII；打印字串用纯英文/数字 |
| 14 | **m_axi 输出缓冲最后一条 cache line 未失效** | 输出末尾几十个子段（如 ch15 尾部）被 CPU 读成 0，表现为「最后一个输出通道/尾部全 0」，改端口/延时/常量维度都无效 | DMA 缓冲**64B 对齐**且长度补齐到 **64 的倍数**（如 400→448），CPU `Xil_DCacheFlushRange/InvalidateRange` 按补齐后长度处理；根因是最后一条部分落在范围内的 cache line 不被失效 |
| 15 | **HLS cosim 2018.3 内建 csim/cosim 工具链** | `csim` 若 tb 签名与设计(`ap_int<8>*`)不符会链接失败；`cosim` 编译到 `iomanip`(需 C++14) 报错 | csim 用**与设计一致的 ap_int 类型**；cosim 的 `iomanip` 是已知工具链问题，可改用**手写 xsim 测试台**或在主机下用 csim 验证 C 模型，再上板 |
| 16 | **加速器输出接下一层输入时 CPU flush 覆盖** | 端到端推理整条链变 0：对加速器输出的中间特征图(fb1/fb2)做了 `Xil_DCacheFlushRange`，把 CPU 缓存的旧 0 刷回 DDR，覆盖了加速器的正确结果 | **只在开始时 flush CPU 写的数据（输入图/权重）**；加速器输出的中间特征图**不要 flush**（它们经 HP0 直写 DDR，CPU 缓存的旧值不能刷回去）；CPU 读加速器输出才用 `Invalidate` |
```
