# 02 · 显示通路（Vivado）说明 —— P2 阶段

> 目标：在 PL 里搭一条"**DDR 帧缓冲 → RGB LCD**"的流水线，供 Linux 的 framebuffer/DRM 驱动使用；
> 并搭一条"**AD9280 采集 → DDR**"的通路给示波器。
> ⚠️ **务必以正点原子《领航者 ZYNQ 之 Linux 开发指南》配套 Vivado 工程为基线**，本文件给的是结构与要点。

---

## 1. 显示流水线组成（Xilinx 标准 IP）

```
   PS(DDR) ──AXI──> AXI VDMA ──MM2S(AXI4-Stream)──> AXI4-Stream to Video Out ──> RGB/LCD 时序输出 ──> 7寸LCD排线
                       ▲                                    ▲
                       │                                    │
                  AXI-Lite 控制                          Video Timing Controller(v_tc)
                  (PS 配置寄存器)                          (产生 1024x600 时序)
```

| IP | vlnv(2018.3) | 作用 |
|---|---|---|
| ZYNQ7 PS | `xilinx.com:ip:processing_system7:5.5` | 官方板级配置（MIO/DDR/UART/SD），开 GP0 + HP0 |
| AXI VDMA | `xilinx.com:ip:axi_vdma:6.3` | DDR 帧缓冲 ⇄ AXI4-Stream |
| Video Timing Controller | `xilinx.com:ip:v_tc:6.2` | 产生显示时序（1024×600） |
| AXI4-Stream to Video Out | `xilinx.com:ip:v_axi4s_vid_out:4.0` | Stream → 并行视频 |
| AXI GPIO | `xilinx.com:ip:axi_gpio:2.0` | LCD 背光/复位/使能 |

> LCD 的 RGB + HSYNC/VSYNC/DE/PCLK 引脚：由 `v_axi4s_vid_out` 输出（必要时加一级自定义 `lcd_out` RTL 做位宽/电平匹配），**引脚约束 XDC 必须按你 7 寸屏的排线定义写**（这一步最容易出错）。

## 2. 关键设置

- **VDMA**：Memory Map Data Width = 64，Stream Data Width = 32（或 24）；勾 **Enable 写/读通道**（示波器采集要 S2MM 写通道）。
- **v_tc**：生成模式；**Frame Rate / 分辨率 1024×600**（时序可按正点原子给的参数）。
- **像素格式**：RGB888(24bit) 或 RGB565(16bit)；与 Linux `xilinx_drm`/fb 的 `bits-per-pixel` 一致。
- **AXI 互联**：显示通路常用 `smartconnect`；**再次强调 NUM_MI≥2**（我们裸机阶段踩过的坑：单从机互联会卡死）。
- **地址**：VDMA/GPIO 走 GP0；VDMA 的 MM2S/S2MM 主口走 **HP0**（直读/写 DDR，和我们的 CNN 加速器同一思路）。

## 3. AD9280 采集通路（**本板不做**，示波器改到野火板）
> 本板只做"系统 + 屏幕"，不需要采集通路。以下内容留作参考，先不实现。
> 若要在本板加采集，再按下面做（采集 RTL 见 `_搁置_示波器/adc_capture.v`）。

```
   AD9280(并行ADC) ──> PL采集RTL(打拍/跨时钟/打包) ──AXI4-Stream──> VDMA S2MM ──> DDR
                                                                        │
                                                              应用读DDR画波形
```

- AD9280 是 8-bit 并行 ADC。PL 侧采集：用采样时钟把数据打拍，凑成 AXI4-Stream 写入 VDMA 的 **S2MM** 通道。
- 采样率由你给的采样时钟决定（AD9280 上限较高，但 PL 侧要控制吞吐，别撑爆 VDMA/DDR）。
- Linux 侧通过 VDMA 的 `/dev/video*` 或自研 `uio`/字符设备读出。

## 4. 导出硬件（沿用我们已跑通的写法）

WebPACK 下 `write_hw_platform` 不可用，改用：
```tcl
write_sysdef -hwdef <impl>/design_1_wrapper.hwdef -bitfile <board>/chain_lcd.bit -file <board>/chain_lcd.sysdef -force
# 再把 .sysdef 复制为 .hdf 交给 PetaLinux
```
（与 `构建脚本/generate_hdf_m4b5.tcl` 同一套方法。）

## 5. 本目录 `run_bd_display.tcl`

提供了一个**起点脚本**：建 PS7（与我们所有工程一致的官方板级配置）+ VDMA + v_tc + v_axi4s_vid_out + GPIO 的基本骨架。
**它是参考，不是成品**：LCD 引脚约束、时序参数、位宽必须按你的 7 寸屏与正点原子工程补全后再综合。
