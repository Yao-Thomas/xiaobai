# 板卡配置（Board Configuration）—— 正点原子 领航者 ZYNQ 7020（V2）

> 依据：正点原子官方资料盘 A 盘（`4_Source_Code\2_Embedded_Vitis\ZYNQ_Vitis_7020.rar`
> 内 `system_processing_system7_0_0\ps7_parameters.xml`），权威、可上板。
> 板卡：**领航者 ZYNQ 开发板 7010/7020 (V2)**；核心板 **V2.5**；底板 **V3.9**（音频 ES8388）。
> 注意：官方例程用 **Vivado/Vitis 2020.2**；本机为 2018.3，配置项名称可能略有差异，
> 但关键 PCW_* 值（DDR/时钟/UART/MIO）跨版本一致，可手动对齐。

## 1. PS（processing_system7）关键配置

| 项目 | 值 |
|---|---|
| PS_CLK 晶振 | **33.333333 MHz** |
| ARM 时钟 (APU) | **666.666666 MHz** |
| MIO Bank0 电压 | **LVCMOS 3.3V** |
| MIO Bank1 电压 | **LVCMOS 1.8V** |

### DDR3
| 项目 | 值 |
|---|---|
| 内存类型 | DDR3（Low Voltage，MT41K256M16 RE-125） |
| 器件型号 | **MT41K256M16 RE-125**（Micron 4Gb/颗） |
| 器件容量 | 4096 MBits / 颗 |
| DRAM 位宽 | 16 Bits |
| 总线位宽 | **32 Bit**（2 颗并 → 约 1GB） |
| speed bin | DDR3_1066F |
| 频率 | **533.333 MHz** |
| CL / CWL / AL | 7 / 6 / 0 |
| 行/列/块地址 | 15 / 10 / 3 |
| ECC | Disabled（本板 x32，非 ECC） |
| 数据训练 | TRAIN_WRITE_LEVEL / READ_GATE / DATA_EYE 均开启 |

### 启动 / I/O
| 项目 | 值 |
|---|---|
| QSPI Flash | 启用，MIO 1..6（启动 flash） |
| SD0 | 启用，MIO 40..45；CD = MIO 10 |
| **UART0（控制台）** | **启用，MIO 14..15，115200** |
| UART1 | 关闭 |
| ENET0 / USB0 / TTC0 / CAN | 关闭（本参考工程） |
| M_AXI_GP0 / GP1 / S_AXI | 本参考工程关闭（PS-only 例程）；我们设计需 **M_AXI_GP0=1** |

> 说明：以上是 ALIENTEK 这套 Zynq 系统的**基础 PS 配置**（DDR/时钟/UART/MIO/boot）。
> 不同例程会在此之上启停各自的 PL 外设。跑 CPU-FPGA 链路时，只需在基础配置上
> **打开 M_AXI_GP0 与 FCLK_CLK0**，其余保持官方默认即可。

## 2. 需要打开的（对我们 CPU-FPGA-NPU 链路）
- `M_AXI_GP0` = 1（PS 作为 AXI 主机访问 PL 加速器）
- `FCLK_CLK0` = 100 MHz（PL 时钟，供 AXI 互联/加速器）
- DDR3、UART0(MIO14/15)、QSPI、SD0 按上表保持官方配置

## 3. 外设引脚（PL 侧，来自 NAVIGATOR_ZYNQ_IO.xdc）

| 功能 | 引脚 | 备注 |
|---|---|---|
| sys_clk（PL 时钟） | U18 | 50MHz（xdc: period 20ns） |
| sys_rst_n（复位） | N16 | 低有效 |
| led[0] / led[1] | H15 / L15 | 底板 LED |
| key[0] / key[1] | L14 / K16 | 底板按键 |
| beep | M14 | 蜂鸣器 |
| uart_rxd / uart_txd（USB UART，PL EMIO） | T19 / J15 | USB 串口 |
| IIC scl/sda | E18 / F17 | EEPROM/RTC/音频 |
| 详见 `NAVIGATOR_ZYNQ_IO.xdc` | — | 完整全表 |

## 4. 文件位置（本机）
- 官方 XDC：`D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)\3_开发板原理图和硬件相关文件\NAVIGATOR_ZYNQ_IO.xdc`
- 官方原理图（底板 V3.9 / 核心板 V2.5）：同目录下 PDF
- 官方 Ps7 参数（参考工程提取）：`board\ref_ps\ps7_parameters.xml`、`ps7_init.c`（本工程内）

## 5. 结论 / 下一步（板级对齐）
- 用上面的 PS 配置替换我们 2018.3 工程里 `processing_system7` 的默认配置
  （DDR3=MT41K256M16 RE-125 / x32 / 533MHz；UART0=MIO14/15；bank0=3.3V bank1=1.8V）。
- 把官方 `NAVIGATOR_ZYNQ_IO.xdc` 加入工程的管脚约束（LED/按键/串口等）。
- 上板验证（等板子到货）。
