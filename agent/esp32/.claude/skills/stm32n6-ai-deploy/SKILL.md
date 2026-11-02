---
name: stm32n6-ai-deploy
description: STM32N6/N647/N657 (Neural-ART NPU) 端侧 AI 模型真机部署完整指南 + 血泪踩坑记录。适用：ST Edge AI 生成的 ATON C 代码集成到 CubeIDE 工程（XSPI2 XIP 场景，如正点原子 ATK-CNN647B）。触发：STM32N6 AI 部署、NPU 推理、ST Edge AI、ATON runtime、stai、网络权重加载 0x71000000、XSPI2 初始化、模型转 C 代码。
---

# STM32N6 端侧 AI 部署（ST Edge AI / ATON runtime）

把训练好的 INT8 模型部署到 STM32N6 真机跑 NPU 推理的完整流程。本 skill 是实战总结，重点是**踩坑**和**验证清单**，不是泛泛而谈。

## 1. 平台与硬件

- **芯片**：STM32N647 = STM32N657 同芯片（Cortex-M55 + Neural-ART NPU 600 GOPS，4.2MB SRAM，flashless）
- **参考板**：正点原子 ATK-CNN647B（VFBGA264 封装）
  - XSPI1 = HyperRAM（W958D8NBYA5I）@ 0x90000000
  - XSPI2 = NOR Flash（MX25UM25645G，32MB）@ 0x70000000
- **关键地址**（由 ST Edge AI 生成 + linker 决定）：
  - 程序代码：`0x70100400`（ROMxspi2_RAMxspi1 linker，**从 XSPI2 NOR 执行 XIP**）
  - 权重：`0x71000000`（octoFlash，`network_atonbuf.xSPI2.raw` 烧到这里）
  - 激活缓冲区：cpuRAM2 `0x34100000` + npuRAM3/4/5 `0x34200000-0x343C0000`（**NPU 私有 SRAM**）

## 2. 模型转换链

```
PyTorch → FP32 ONNX → INT8 QDQ ONNX → ST Edge AI 生成 C 代码
```

ST Edge AI 输出（在 `st_ai_output/`）：
- `network.c` / `network.h`（模型结构）
- `stai_network.c` / `stai_network.h`（stai API 封装）
- `network_atonbuf.xSPI2.raw` / `.bin`（权重，**烧到 0x71000000**）
- `network_generate_report.txt`（内存分配报告，必读！）

## 3. 工程集成步骤

1. 把 `network.c`、`stai_network.c` 拷到 `Core/Src/`，`network.h`、`stai_network.h` 拷到 `Core/Inc/`
2. `.cproject` 加编译宏和库：
   - 宏：`LL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6`、`LL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL`、`LL_ATON_RT_MODE=LL_ATON_RT_ASYNC`、`LL_ATON_DBG_BUFFER_INFO_EXCLUDED=1`
   - 库：`NetworkRuntime1201_CM55_GCC.a`（在 `Middlewares/ST/AI/Lib/GCC/ARMCortexM55/`）
   - include：`Middlewares/ST/AI/Inc`、`Middlewares/ST/AI/Npu/ll_aton`、`Middlewares/ST/AI/Npu/Devices/STM32N6xx`、`Middlewares/ST/AI/Reloc/Inc`
3. 启用 `HAL_CACHEAXI_MODULE_ENABLED`（在 `stm32n6xx_hal_conf.h`）
4. 确保 `stm32n6xx_hal_cacheaxi.c` 被编译（CubeMX 链接工程要 Refresh 才能识别新文件，见踩坑 #6）
5. linker 用 `ROMxspi2_RAMxspi1.ld`

## 4. 关键踩坑（血泪教训，逐条必看）

### 坑 #1：XIP 冲突 —— 程序从 XSPI2 执行，绝不能重新初始化 XSPI2 ⚠️最致命

程序代码在 XSPI2 NOR（XIP）。**Appli 里绝对不能调用 `MX_XSPI2_Init()` 或任何重新配置 XSPI2 的代码**——改正在执行代码的外设时钟 = 硬件错误/卡死。

- FSBL 启动时已经把 XSPI2 配好 memory-mapped（否则程序跑不起来）
- 权重在 0x71000000 **直接可读，不需要任何 XSPI2 初始化**
- 症状：LED 不亮 + 卡在 `HAL_RCCEx_PeriphCLKConfig`（XSPI2 时钟 mux 写入那步）

### 坑 #2：VDDIO3 电压 = 1.8V，不是 3.3V

ATK-CNN647B 的 XSPI2 NOR Flash 是 **1.8V 域**。VDDIO3 必须配 1.8V：
```c
HAL_PWREx_EnableVddIO3();
HAL_PWREx_ConfigVddIORange(PWR_VDDIO3, PWR_VDDIO_RANGE_1V8);
```
配 3V3 会导致 GPIO/LED 异常。`.ioc` 里 `PWR.PowerDomain3=PWR_VDDIO_RANGE_1V8`。

### 坑 #3：NPU RAM 使能 —— 推理卡死 WFE 的根因 ⚠️最关键

激活缓冲区在 **NPU 私有 SRAM（AXISRAM3/4/5）**，这些 RAM 默认没使能！NPU 一访问激活区就卡死在 WFE 死等。必须在 NPU 使用前加（照官方 hello_world 的 `system_init_post()`）：
```c
__HAL_RCC_SYSCFG_CLK_ENABLE();
__HAL_RCC_CRC_CLK_ENABLE();
RCC->MEMENR |= RCC_MEMENR_AXISRAM3EN | RCC_MEMENR_AXISRAM4EN
            | RCC_MEMENR_AXISRAM5EN | RCC_MEMENR_AXISRAM6EN;
RCC->MEMENR |= RCC_MEMENR_CACHEAXIRAMEN;
RAMCFG_SRAM2_AXI->CR &= ~RAMCFG_CR_SRAMSD;
RAMCFG_SRAM3_AXI->CR &= ~RAMCFG_CR_SRAMSD;
RAMCFG_SRAM4_AXI->CR &= ~RAMCFG_CR_SRAMSD;
RAMCFG_SRAM5_AXI->CR &= ~RAMCFG_CR_SRAMSD;
RAMCFG_SRAM6_AXI->CR &= ~RAMCFG_CR_SRAMSD;
MEMSYSCTL->MSCR |= MEMSYSCTL_MSCR_DCACTIVE_Msk | MEMSYSCTL_MSCR_ICACTIVE_Msk;
```

### 坑 #4：WFE 时钟睡眠门控

Bare-metal 的 `LL_ATON_OSAL_WFE()` = `__WFE()`。NPU 执行时 CPU 进 WFE 睡眠，若时钟被门控，NPU/CACHEAXI/内存时钟会关掉 → NPU 卡死。加 `set_clk_sleep_mode()`：
```c
__HAL_RCC_DBG_CLK_SLEEP_ENABLE();
__HAL_RCC_XSPIPHYCOMP_CLK_SLEEP_ENABLE();
__HAL_RCC_AXISRAM1_MEM_CLK_SLEEP_ENABLE();  // ...RAM1~6
__HAL_RCC_CACHEAXIRAM_MEM_CLK_SLEEP_ENABLE();
__HAL_RCC_RIFSC_CLK_SLEEP_ENABLE();
__HAL_RCC_RISAF_CLK_SLEEP_ENABLE();
__HAL_RCC_IAC_CLK_SLEEP_ENABLE();
__HAL_RCC_XSPI1_CLK_SLEEP_ENABLE();
__HAL_RCC_XSPI2_CLK_SLEEP_ENABLE();
__HAL_RCC_CACHEAXI_CLK_SLEEP_ENABLE();
__HAL_RCC_NPU_CLK_SLEEP_ENABLE();
__HAL_RCC_USART1_CLK_SLEEP_ENABLE();
```

### 坑 #5：NPU 初始化序列（照官方 NPU_Config）

```c
__HAL_RCC_NPU_CLK_ENABLE();
__HAL_RCC_NPU_FORCE_RESET();
__HAL_RCC_NPU_RELEASE_RESET();
__HAL_RCC_CACHEAXI_CLK_ENABLE();
__HAL_RCC_CACHEAXI_FORCE_RESET();
__HAL_RCC_CACHEAXI_RELEASE_RESET();
npu_cache_enable();   // 来自 npu_cache.h，会 HAL_CACHEAXI_Init + Enable
HAL_RIF_RISC_SetSlaveSecureAttributes(RIF_RISC_PERIPH_INDEX_NPU, RIF_ATTRIBUTE_PRIV | RIF_ATTRIBUTE_SEC);
```

### 坑 #6：CubeMX 链接工程加新 .c 文件不自动识别

CubeMX 生成的 FSBL/Appli 结构里，`Drivers/` 每个源文件是 `<link>` 单独链接的，**命令行拷进去的新文件 CubeIDE 不识别**，makefile 每次重建会覆盖手工修改。可靠做法：
- 把新 `.c` 放到 **`Core/Src/`**（真实文件夹，会重新扫描）
- 或右键工程 Refresh(F5) + Clean 重建
- 头文件放 `Drivers/Inc` 即可（include 路径能找到）

### 坑 #7：错误码诊断

推理/初始化返回 `stai_return_code`，用 6 位 hex 打印诊断：
- `0x040040` = 权重指针错；`0x040000` = 激活缓冲错；`0x040010` = 输入指针错

## 5. stai API 推理代码模板

```c
#include "stai_network.h"
#include "npu_cache.h"

STAI_NETWORK_CONTEXT_DECLARE(network, STAI_NETWORK_CONTEXT_SIZE)

// 初始化（XSPI2 不碰！）
stai_runtime_init();
stai_network_init(network);

// 拿输入输出缓冲区
stai_ptr in[STAI_NETWORK_IN_NUM];
stai_ptr out[STAI_NETWORK_OUT_NUM];
stai_size in_len, out_len;
stai_network_get_inputs(network, in, &in_len);
stai_network_get_outputs(network, out, &out_len);

// 填输入（int8，尺寸 STAI_NETWORK_IN_1_SIZE_BYTES）
for (uint32_t i = 0; i < STAI_NETWORK_IN_1_SIZE_BYTES; i++) in[0][i] = 0;

// 推理（同步模式最简单）
stai_return_code rc = stai_network_run(network, STAI_MODE_SYNC);

// 读输出（int8，需反量化）。尺寸见 network.h：OUT_1~OUT_4_SIZE_BYTES
```

## 6. 验证清单（按顺序，改 1 验 1）

1. **LED 亮** → 基础运行正常，XSPI2 没被误碰
2. **权重可读** → 读 `0x71000000` 前 4 字节，应等于 `network_atonbuf.xSPI2.raw` 文件头（本例 `c9 e3 fb f9`）。是 FF 说明权重没烧
3. **AI init 成功** → `stai_runtime_init()` 和 `stai_network_init()` 都返回 0（打印 R000000 N000000）
4. **推理成功** → `stai_network_run(STAI_MODE_SYNC)` 返回 0，有耗时和输出。卡住不出结果 = NPU RAM 没使能（坑 #3）

## 7. 参考来源（磁盘上就有）

- **ST 官方**：`D:\ST\STEdgeAI\4.0\Projects\STM32N6570-DK\Applications\hello_world\`（`system_init_post`、`NPU_Config`、`RISAF_Config`、`set_clk_sleep_mode` 都在 `Src/misc_toolbox.c`）
- **ATK 官方 FSBL**：`D:\ST\STM32IDE_Workspace\Software_Package\FSBL\MX25UM25645G_W958D8NBYA5I_Example\`
- **ATK 官方 External Loader**（烧权重用的 .stldr）：`D:\ST\STM32IDE_Workspace\Software_Package\External_Loader\MX25UM25645G_ATK-CNN647B\`
- **板级引脚表**：`C:\Users\姚恩奇\n647_schematics\cnn647b_pins_Sheet1.csv`

## 8. 硬件事实速查

| 项 | 值 |
|---|---|
| XSPI2 引脚 | GPION：PN0(DQS) PN1(NCS) PN2-5(D0-3) PN6(CLK) PN8-11(D4-7)，AF9_XSPIM_P2 |
| XSPI2 MemoryType | HAL_XSPI_MEMTYPE_MACRONIX（不是 HYPERBUS） |
| XSPI2 WrapSize | HAL_XSPI_WRAP_NOT_SUPPORTED |
| XSPI2 时钟源 | HCLK（ATK 官方 ExtMemLoader 用 HCLK；N6570-DK 用 IC3） |
| 权重地址 | 0x71000000（octoFlash） |
| 权重文件头 | c9 e3 fb f9（`network_atonbuf.xSPI2.raw`） |
