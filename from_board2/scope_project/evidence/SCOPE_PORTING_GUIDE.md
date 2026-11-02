# Zynq-7020 双通道示波器 —— 移植与工程说明

> 目标读者：把这套**示波器部分**移植到另一块**同核心（Zynq-7020 / xc7z020）**板子上的工程师。
> 本文把 PL（FPGA）侧、PS（ARM/Linux）侧、UI 侧全部讲清楚，并给出移植工作流。
>
> 生成时间：2026-10-10　目标器件：`xc7z020clg400-2`（正点原子 领航者 zynq01）

---

## 一、整体架构（三层分离）

```
┌────────────────────────── PS（ARM Cortex-A9 / Linux）──────────────────────────┐
│                                                                              │
│   apps_scope_dual.py   界面：三档刷新、五项调节、弹层、AUTO                    │
│          │                                                                   │
│   scope_model.py       全部配置状态（通道/触发/采集/显示），原子 commit()      │
│          │                                                                   │
│   scope_processing.py  算法：时基表、两点标定、直方图/分位、包络、迟滞边沿      │
│          │                                                                   │
│   scope_dual.py        ctypes 封装 libscopedual.so，寄存器读写 + 帧缓存        │
│          │                                                                   │
│   libscopedual.so      C：/dev/mem mmap 寄存器；sd_measure 帧测量（热路径）    │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ AXI4-Lite @ 0x43CC0000（64K）
┌──────────────────────────────────┴───────────────────────────────────────────┐
│                          PL（FPGA）                                           │
│                                                                              │
│   scope_dual_axi.v     寄存器组 + 测试波形发生器 + 诊断计数                    │
│          │                                                                   │
│   scope_dual_core.v    抽取 → 双 bank 环形写 → 迟滞触发 →                      │
│                        帧统计引擎 → 列包络引擎 → Bank 锁定/ACK                 │
│                                                                              │
│   时钟：scope_adc_clk (clk_wiz)                                               │
│          in 100MHz (FCLK_CLK0)                                               │
│          clk_out1 = 20 MHz          → adc_ref_clk（ADC 锁存）                 │
│          clk_out2 = 20 MHz @270°    → sample_clk（采样，错开数据窗口）        │
│   数据：adc1_data[9:0] / adc2_data[9:0]  ← 外部引脚                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

**核心设计原则**：**逐点/逐像素的运算一律放 PL**，PS 只做寄存器读写、帧搬运、UI 绘制与常数级换算。
（反例：4096 点逐点扫描放 Python → 0 FPS；放 C → 17 FPS；放 PL → 60 FPS 量级）

---

## 二、资源占用（`out/utilization.rpt`，xc7z020clg400-2）

| 资源 | 已用 | 总量 | 占用 | 空闲 |
|---|---|---|---|---|
| Slice LUTs | **20,146** | 53,200 | 37.87% | 33,054 |
| └ LUT as Logic | 17,160 | 53,200 | 32.26% | |
| └ LUT as Memory | 2,986 | 17,400 | 17.16% | |
| Slice Registers | **26,986** | 106,400 | 25.36% | 79,414 |
| Block RAM Tile | **10** | 140 | 7.14% | 130 |
| DSP48E1 | **2** | 220 | 0.91% | 218 |
| Bonded IOB | **81** | 125 | **64.80%** | 44 ← 唯一紧张项 |
| BUFGCTRL | 9 | 32 | 28.13% | 23 |

**时序**：`All user specified timing constraints are met` ✓

### 示波器自身的增量（相对接入前的基线）

| 项目 | 增量 |
|---|---|
| LUT | **+2,852** |
| FF | **+1,246** |
| BRAM | **+0**（包络用 5 块 BRAM 从原有额度内） |
| DSP | **+0** |

> ★ 关键结论：**核心采集逻辑本身非常省**（`scope_dual_core` 单独综合只有 **2,839 LUT / 1,045 FF**）。
> 上面 20,146 是整个设计（含 LCD/GPU/音频等既有外设）的总量。

### 为 int8 CNN 预留的额度（硬约束，不许突破）

| 资源 | 预留 | 本设计实际 | 结论 |
|---|---|---|---|
| DSP48E1 | ≥ 64 | 2 | 未动 ✓ |
| Block RAM | ≥ 24 | 10 | 未动 ✓ |
| Slice LUTs | ≥ 15,000 | 20,146 ≤ 43,200 上限 | 守住 ✓ |

---

## 三、PL 侧（RTL）详解

### 3.1 `rtl/scope_dual_core.v`（580 行）—— 采集引擎

**参数**
```verilog
parameter integer ADDR_WIDTH = 12,   // 4096 点
parameter integer DEPTH      = 4096
```

**端口分组**

| 组 | 端口 | 说明 |
|---|---|---|
| 时钟/复位 | `sample_clk`, `rst_n` | 20 MHz @270° |
| 控制 | `start_pulse`, `stop_pulse` | 单周期脉冲 |
| 配置 | `cfg_decimation[15:0]` | 抽取倍率 D |
| | `cfg_trigger_level[9:0]` | 触发电平 |
| | `cfg_trigger_edge` | 0=上升 1=下降 |
| | `cfg_trigger_mode[1:0]` | AUTO/NORMAL/SINGLE/ROLL |
| | `cfg_trigger_source[1:0]` | CH1/CH2/外部 |
| | `cfg_trigger_hys[9:0]` | 迟滞宽度（施密特） |
| | `cfg_pretrigger[11:0]` | 预触发点数 |
| | `cfg_acq_roll`, `cfg_free_run` | Roll / 自由运行 |
| 数据 | `adc1_data[9:0]`, `adc2_data[9:0]` | 直接来自引脚 |
| 状态 | `busy`, `done`, `triggered`, `completed_bank` | |
| | `start_addr`, `write_total`, `frame_sequence` | 帧描述符 |
| | `trigger_index`, `frame_triggered`, `frame_decimation` | |
| | `lost_frames[15:0]` | **Bank 未 ACK 丢帧计数** |
| 读口 | `rd_clk`, `rd_addr`, `rd_data[19:0]` | 跨时钟域读 bank |
| Bank 握手 | `bank_lock_req`, `bank_lock_bank`, `bank_ack`<br>`bank_locked`, `bank_locked_bank` | **防拼接帧** |
| 帧统计 | `st_min1/2`, `st_max1/2` | 帧内极值 |
| | `st_sum1/2[31:0]` | 累加和（PS 除出均值） |
| | `st_clip_lo1/2`, `st_clip_hi1/2[15:0]` | 贴 0 / 贴 1023 计数 |
| | `st_edges1/2[15:0]` | 迟滞边沿数 |
| | `st_span1/2[15:0]` | 首末边沿间隔 |
| | `st_n[15:0]`, `st_valid` | 统计点数 / 就绪 |
| 列包络 | `env_rd_col[10:0]`, `env_rd_data[19:0]` | bit10=通道, bit9:0=列号 |
| | `cfg_win_start[11:0]`, `cfg_win_len[12:0]` | 可配置显示窗口 |
| | `cfg_col_step[23:0]` | **DDA 列号步进（PS 算好下发）** |
| Roll | `roll_ptr_out[12:0]`, `roll_fill_out[12:0]` | |

**内部数据通路**

```
adc1/2_data
   │
   ├─[抽取 D]── write_sample ──┬─→ sample_mem（双 bank 环形，BRAM）
   │                           │
   │                           ├─→ 帧统计引擎（流式，零额外扫描）
   │                           │     min/max、sum、clip、迟滞边沿数、首末边沿间隔
   │                           │
   │                           └─→ 列包络引擎（DDA 列号 + 两拍流水 RMW）
   │                                 env1_mem / env2_mem（1008×20bit BRAM）
   │
   └─→ 迟滞（施密特）触发状态机 ──→ 触发点 → busy/done 状态机
                                        │
                                        └─→ Bank 锁定/ACK（can_publish）
```

**★ 三个必须知道的设计要点**

1. **列号用 DDA（增量累加），不是除法**
   ```verilog
   always @(posedge sample_clk) begin
       if (start_pulse) col_acc <= 0;
       else if (write_sample && in_win) col_acc <= col_acc + cfg_col_step;
   end
   wire [10:0] col_now1 = col_acc[26:16];
   ```
   `cfg_col_step = round(1008 × 65536 / win_len)` 由 **PS 用 Python 算好下发**（PS 算除法不要钱）。
   **曾经写成 `(idx<<12)/win_len` → 综合出除法器 → place 直接失败。**

2. **包络 BRAM 的读-改-写必须拆成两拍流水**
   ```verilog
   // 第 1 拍：读旧值
   env_rd1 <= env1_mem[col_now1];
   env_we_d <= write_sample && in_win;
   env_col_d <= col_now1;
   // 第 2 拍：比较并写回
   if (env_we_d) env1_mem[env_col_d] <= {max(...), min(...)};
   ```
   **写成同拍 `env1_mem[col] <= f(env1_mem[col])` → Vivado 无法推断 BRAM →
   整块 1008×20 退化成触发器 → +40,320 FF / +26,000 LUT → LUT 82% → place 失败。**

3. **Bank 没 ACK 前绝不覆盖**
   宁可丢帧并累加 `lost_frames`，也不产生**拼接帧**。

### 3.2 `rtl/scope_dual_axi.v`（650 行）—— 寄存器接口

- 标准 Xilinx AXI4-Lite Slave 模板（`S_AXI`）
- `C_S_AXI_ADDR_WIDTH = 12`（字索引 `awaddr_hold[11:2]`，可寻址 1024 个字）
- 内含：寄存器组、测试波形发生器（`TESTPAT`）、诊断计数（`CLKCNT`/`ACT`/`EVER`）
- 把 `sample_clk` 域的脉冲/配置与 `aclk`（100 MHz）域做同步

**寄存器地图**（完整版见 `release_candidate/AXI_REGISTER_MAP.md`）

| 字 | 名称 | 说明 |
|---|---|---|
| 0x00 | CTRL | bit0 翻转启动 / bit1 停止 |
| 0x01 | ENV_DATA | **读：包络数据，硬件自动 +1 列**；到 1007 列翻到另一通道 |
| 0x03 | DEC | 抽取倍率 |
| 0x04 | ENV_PTR | 写：起始列（bit10=通道） |
| 0x05 | TRIGLEV | 触发电平 |
| 0x06 | TRIGCFG | bit0 边沿 / [2:1] 模式 / [4:3] 触发源 |
| 0x07 | PRE | 预触发点数 |
| 0x0D | VERSION | 魔数 `0x53435034`（"SCP4"） |
| 0x0E | CAPS | 能力位 |
| 0x0F | RATE | 采样率（20 MHz） |
| 0x10 | FRAMESEQ | 帧序号 |
| 0x11/0x12 | DESC0/DESC1 | {bank, start_addr} / sample_count |
| 0x13 | TRIGIDX | 触发点在帧内位置 |
| 0x14 | LOST | 丢帧计数 |
| 0x15 | LOCK | bit0 锁定请求 / bit1 bank / bit2 应答 |
| 0x16 | FLAGS | bit0 triggered / bit1 locked / bit2 busy |
| 0x18 | HYS | 迟滞宽度 |
| 0x19 | ACQMODE | 0=Auto 1=Normal 2=Single 3=Roll |
| 0x1F | TESTPAT | !=0 时用内部测试波形 |
| 0x20~0x28 | ST_* | **帧统计：{max,min} / sum / clip / edges / span / n** |
| 0x29 | WIN_START | 显示窗口起点 |
| 0x2A | WIN_LEN | 显示窗口长度 = `Timebase.span` |
| 0x2B | COL_STEP | **列号 DDA 步进**（PS 算好下发） |

### 3.3 IP 打包

```tcl
# scripts/package_scope_dual_ip.tcl
VLNV      : dsh:user:scope_dual_axi:1.0
IP 仓库   : ip_repo/scope_dual_axi/
源文件    : rtl/scope_dual_axi.v  +  rtl/scope_dual_core.v
```

### 3.4 BD 集成（`scripts/build_scope_dual.tcl`）

```tcl
# 时钟
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 scope_adc_clk
set_property -dict {
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ  {20.000}    ;# adc_ref_clk
    CONFIG.CLKOUT2_USED                {true}
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ  {20.000}    ;# sample_clk
    CONFIG.CLKOUT2_REQUESTED_PHASE     {270.000}   ;# ★ 错开 ADC 数据窗口
} $scope_adc_clk
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins scope_adc_clk/clk_in1]

# 示波器 IP
create_bd_cell -type ip -vlnv dsh:user:scope_dual_axi:1.0 scope_dual_0
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M17_AXI] [get_bd_intf_pins scope_dual_0/S_AXI]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0]     [get_bd_pins scope_dual_0/aclk]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]  [get_bd_pins scope_dual_0/aresetn]
connect_bd_net [get_bd_pins scope_adc_clk/clk_out1] [get_bd_pins scope_dual_0/adc_ref_clk]
connect_bd_net [get_bd_pins scope_adc_clk/clk_out2] [get_bd_pins scope_dual_0/sample_clk]

# 数据引脚透到顶层
connect_bd_net [get_bd_ports adc1_data] [get_bd_pins scope_dual_0/adc1_data]
connect_bd_net [get_bd_ports adc2_data] [get_bd_pins scope_dual_0/adc2_data]
```

**AXI 基地址：`0x43CC0000`，范围 64K**（`scope_dual.c` 头部注释 + `scope_dual.py` 的 `DEFAULT_BASE`）

### 3.5 约束（`constraints/scope_dual.xdc`）

```tcl
# ADC 输入时序（相对 clk_out1，20 MHz）
set_input_delay -clock [get_clocks clk_out1_system_scope_adc_clk_0] -max 25.000 \
    [get_ports {adc1_data[*] adc2_data[*]}]
set_input_delay -clock [get_clocks clk_out1_system_scope_adc_clk_0] -min  0.000 \
    [get_ports {adc1_data[*] adc2_data[*]}]

# ★ 包络 BRAM 的跨时钟域（写 20MHz / 读 100MHz）
#   两个时钟同源异相，工具会按最紧 setup 查（实测 req 2.5ns，实际 3.3ns，违例 -0.229ns）。
#   包络数据整帧不变，属合法 CDC -> 用 datapath_only 放宽到 12ns，
#   既消除假违例，又保留真实约束（不像 set_false_path 完全放弃检查）。
set_max_delay -datapath_only 12.000 \
    -from [get_clocks clk_out2_system_scope_adc_clk_0] \
    -to   [get_cells -hierarchical -filter {NAME =~ *capture_core/env_rd_data_reg*}] \
    -quiet
```

**ADC 引脚（J4，反插 180°）**：`adc1_data[0]`=V15 … `adc1_data[9]`=U13；
`adc2_data[0]`=V11 …（完整表见 `constraints/scope_dual.xdc` 第 93~130 行）

---

## 四、PS 侧详解

### 4.1 `ps/scope_dual.c`（1061 行）→ `libscopedual.so`

**职责**：寄存器读写 + **热路径测量**（替代 Python 逐点循环）

| 关键点 | 说明 |
|---|---|
| 打开 | `open("/dev/mem"); mmap(64K, base=0x43CC0000)` |
| 访问 | `sd_rd(off) { return REG[off/4]; }` —— **参数是字节偏移** |
| 帧读取 | `sd_read_frame_locked()`：先 Bank 锁定 → 读 → ACK（防拼接帧） |
| 非阻塞 | `sd_poll_frame()` + `sd_wait_us()`（真实微秒超时，不是循环计数） |
| **`sd_measure`** | 帧测量：直方图 → **1%/99% 分位**得稳健极值 → 迟滞判边沿 → 跳变沿估周期 |
| `sd_saturation` | 贴 0 / 贴 1023 计数，判过量程 |
| `sd_read_envelope` | 一次读 1008 列 × 2 通道（**2016 次单事务**，原逐点读是 8192 次） |
| `sd_hdash` / `sd_vdash` | 在 RGB 缓冲上画横/竖虚线（触发电平线 / 水平位置线） |
| `sd_draw_env` | 把包络画进 RGB 缓冲（min/max 竖条） |

**★ `sd_measure` 里两个反复踩过的坑**

1. **零迟滞的中点比较会数出上千个假边沿**
   ```c
   // ✗ 错的：只要跨过中点就计数
   if (smp[i-1] < mid && smp[i] >= mid) edges++;
   // ✓ 对的：施密特迟滞（先回到 mid-hys 以下武装，再升到 mid+hys 以上才计）
   ```
   实测 7 LSB 噪声会数出 **1010 个假边沿** → 频率显示 4.93 MHz（真实≈0）。

2. **只用上升沿 → 整帧不到 2 个周期就测不出频率**
   → 改成 **上升+下降双向穿越**，再找**大幅跳变沿（回扫）** 的间隔当整周期。

3. **`out[4]` 的语义**：现在是**整周期点数**（不是首末间隔）。
   UI 侧 `freq = 1/(out[4] × dt)`。

### 4.2 `ps/scope_dual.py`（636 行）—— ctypes 封装

- `DEFAULT_BASE = 0x43CC0000`，也可从标记文件读
- `class ScopeDual`：`set_acqmode/set_dec/set_hys/configure/roll_start/`
  `read_frame_locked/read_roll/read_envelope/envelope_into/set_window/read_stats/`
  `set_testpat/set_trigcfg`
- **能力检测**：`VERSION` 魔数（`0x53435034`="SCP4"）判断新老 IP

### 4.3 `ps/scope_processing.py`（517 行）—— 算法层

| 内容 | 要点 |
|---|---|
| `TIME_DIV` | **全系统唯一一张时基表**（16 档，50ns~5ms）。<br>★ 曾经有两张 → 硬件 dec 和算频率用的 dt 不一致 → 频率误差 **25500%** |
| `Timebase` | `window = T/div×10`；`D = ceil(fs×window/4096)`；`span = round(fs×window/D)`；`actual_tdiv` |
| `ChannelCal` | 每通道 `zero`/`gain`，**从 `scope_cal.json` 读**，无文件时用内置默认 |
| `VPP_CAL` + `vpp_correct()` | **Vpp 分段线性标定表**（见下节"电压标定"） |
| `histogram` / `percentile_from_hist` / `robust_limits` | 1024 级直方图 → 1%/99% 分位（忽略孤立毛刺） |
| `hysteresis_edges` / `period_from_edges` | 迟滞边沿 + 周期估计（中位/截尾均值） |
| `measure` | 完整测量（**C 回退路径**用） |
| `envelope` | 半开区间 `[a,e)` 分列（避免相邻列共用边界点导致波形发胖） |

### 4.4 `ps/scope_model.py`（289 行）—— 状态模型

```python
ACQ_AUTO, ACQ_NORMAL, ACQ_SINGLE, ACQ_ROLL = 0, 1, 2, 3

class TriggerModel / AcqModel / DisplayModel / ScopeModel
```

**★ 三个概念必须分开**（用户特别强调）：
- **显示通道 display** — 波形画不画
- **当前调节通道 active** — 面板 `－/＋` 改谁
- **触发源 trig.src** — 拿谁做触发

**配置变更一律走 `ScopeModel.commit(hw)` 原子提交**，UI 不许直接写硬件寄存器。

### 4.5 `ps/apps_scope_dual.py`（1067 行）—— UI

| 要点 | 说明 |
|---|---|
| 三档刷新 | 触摸 8ms（125 Hz）/ 波形 40ms（25 FPS）/ 文字 150ms（6.7 FPS） |
| 只刷变化区域 | `draw_top` / `draw_scales` / `draw_stat` / `draw_cards` / `draw_ctl` 全部**内容键缓存** |
| 五项固定调节 | V/div、垂直位置、Time/div、水平位置、触发电平 + `－/＋` + **归位到 0** |
| 弹层 | 通道（CH1/CH2 复选+确定）、模式（Auto/Normal/Single+确定、高级触发独立页） |
| AUTO | 双击波形区触发；选"已显示且有有效测量"的通道定档；**3 个周期 + 幅度占屏 75% + 水平位置归零**；**启动时自动跑一次** |
| 单位显示 | 垂直位置/触发电平显示**伏**；水平位置显示**时间**；每次步长 = **当前每格值的 0.1 倍** |

**性能优化（实测有效）**：字形缓存（`fbui.text` 单字 1.1ms → 0.53ms）、内容键缓存、
逐项缓存、**缓存粒度要匹配变化粒度**（真实信号有噪声 → `draw_stat` 必须逐格缓存）。
全量重绘 **89 ms → 24.8 ms**，稳态单核 **~88% → 34.6%**。

### 4.6 `ps/fbui.py`（18 KB）—— 框架（与示波器解耦）

- `Screen`：mmap `/dev/fb0`，`mode="RGB"`（**面板是标准 RGB，别再改回 BGR**）
- `blit_raw(x,y,w,h,data)`：不经 PIL 直接贴字节（热路径）
- `Touch`：`os.open(dev, O_RDONLY|O_NONBLOCK)` + 事件解析；**支持 `/tmp/ui_tap` 远程注入**（见下）
- `back_hit(x,y)`：左上角返回区 `[10, 8, 130, 52]`
- `btn/hit/rrect/text/font` 等绘图原语

**★ 离屏测量法（调试神器）**：正常构造 `Screen()`，然后把 `scr.flush` 打桩成空操作 →
**一个字节都不写 `/dev/fb0`，桌面完全不受影响**，但仍能测出真实耗时（热路径用的 `blit_raw` 是真实开销）。

**★ 触摸注入法**：向 `/tmp/ui_tap` 写
```
"x,y"                              单次点击
"down:x,y" / "move:x,y" / "up:x,y" 单独注入（测长按）
"drag:x1,y1;x2,y2"                 拖拽
```

### 4.7 桌面集成（不改操作系统）

- 桌面 `desktop.py` 的应用列表里 `{"name":"示波器","mod":"apps_scope_dual"}`
- 点击时 `importlib.reload(mod)` 后调 `mod.run(scr, touch)`
- **★ 部署只换文件即可**：`sudo cp ... /home/zynq/ui/ && sudo rm -rf __pycache__`
  **不要 `systemctl stop/start zynq-desktop`**（中途失败会留下"文件没换+桌面被停"的假象）
- **★ 注意**：桌面只 reload 应用模块，**不会 reload 它的依赖**（`scope_model`/`scope_processing`）
  → 改了这些必须**重启桌面**才生效

---

## 五、电压标定（重要，容易做错）

### 5.1 为什么不能用"乘一个系数"

真实链路是**两点线性关系**，不是纯比例：

```
V = (LSB − zero) × k        ← 两个未知数
```

用户实测（CH1）：
| 真实 Vpp | 名义显示 | 比值 |
|---|---|---|
| 1 | 1.01 | 1.010 |
| 4 | 4.29 | 1.073 |
| 6 | 6.46 | 1.077 |
| 7 | 7.57 | **1.081** |

**比值不是常数** → 有零点偏移 + 斜率误差 → **单一系数只能修斜率**。
（试过 `V_CAL=0.9384`，被否掉。）

### 5.2 当前实现：Vpp 分段线性表

```python
VPP_CAL = [(0.00,0.00), (1.01,1.00), (4.29,4.00), (6.46,6.00), (7.57,7.00)]
def vpp_correct(v):   # 分段线性插值，超表尾按末段斜率外推
```

**四个点全部 0.00% 误差** ✓
**`Vmax/Vmin` 由「中点 ± Vpp/2」推出** → 三者永远自洽。

### 5.3 ★ 硬限制：Vpp 数据标不出零点

```
vpp = (max−zero)·K·gain − (min−zero)·K·gain = (max−min)·K·gain
                                                  ↑ zero 被消掉
```

**→ 要同时定零点+增益，必须用【直流电平】测。**

### 5.4 标定工具（都在板上 `/home/zynq/ui/`）

```bash
sudo python3 cal_diag.py rep CH1          # 重复性检查（同一信号连读 10 次，看散差）
sudo python3 cal_diag.py dc  CH1 0.0 4.0  # 直流两点标定（零点+增益都能定）★推荐
sudo python3 cal_diag.py pp  CH1 1.0 4.0  # Vpp 两点标定（只能定增益）
sudo python3 cal_scope.py  CH1            # 交互式，读【原始 ADC 码】（不会叠加误差）
sudo python3 cal_from_pairs.py ch0 1.0 0.99 4.0 4.29   # 由「真实/显示」两组数算
```

结果写入 `/home/zynq/ui/scope_cal.json`：
```json
{ "ch0": {"zero": 511.5, "gain": 1.0}, "ch1": {...} }
```

**★ 为什么工具读"原始 ADC 码"**：`sd_measure` 返回的 min/max 是**未经任何标定的原始码**
→ **反复标定永远不会误差累加**（手抄屏幕显示值就会）。

---

## 六、实测性能（改造前后）

| 维度 | 改造前 | 改造后 | 提升 |
|---|---|---|---|
| 帧率 | 8.2 FPS | **40.3 FPS** | 4.9× |
| ARM 单核 CPU | 95~100% | **34.6%** | 2.8× |
| FPGA 帧周期 | 15.7 ms | **0.47 ms** | 33× |
| UI 全量重绘 | 89.39 ms | **24.8 ms** | 3.6× |
| 通道切换 | 158 ms | **83 ms** | 1.9× |
| 模式切换 | 134 ms | **49 ms** | 1.7× |
| Normal 无触发阻塞 | 4000 ms | **0.8 ms** | 5000× |

**AXI 事务数**：每帧 **16384 → 2016**（包络一次读 1008 列 ×2 通道）

---

## 七、工程发展方向

1. **把包络路径修好**（当前 PL 包络只填 95/1008 列，波形临时走 C 回退路径）
   → 定位方法：变 `win_len`(256/512/1024/2048/4096) 与 `dec`(1/2/3/6/12)，
   实测**恒定 95 列**、与两者无关 → 固定比例 9.375% → 指向 `in_win` 门控或
   包络写地址位宽问题。修好后可去掉 C 回退，进一步降 CPU。

2. **多点/查表标定**：把 `VPP_CAL` 扩成多点，每通道独立；再补**直流电平**标定
   （解决 `Vmax/Vmin` 绝对值）。

3. **int8 CNN 接入**（预留额度充足）：独立 IP + 单独时钟 100~150 MHz + AXI HP/DMA，
   **不要塞进 `scope_dual_*`**。

4. **触发增强**：当前是迟滞边沿触发；可加脉宽触发、斜率触发、视频触发。

5. **数学通道**：CH1±CH2、FFT（FFT 应放 PL 或至少 C，不要 Python 逐点）。

6. **深存储**：现在 4096 点；用 DDR + AXI HP 可做到 M 级深存储。

7. **丢帧语义修正**：顶栏 `丢帧` 是 **PL 侧 Bank 未 ACK 丢帧**，不是 UI 丢帧 → 建议改名或分列显示。

---

## 八、移植到同核心新板子 —— 总体思路

**核心判断**：这套示波器的**软件层（PS + UI）与硬件层（PL）是解耦的** ✓
- **PS/UI 几乎可以照搬**（只改 fb 分辨率、触摸设备节点、启动方式）
- **PL 需要重新做 3 件事**：① 时钟 ② 引脚约束 ③ BD 集成

### 8.1 必须改的东西（按优先级）

| # | 项目 | 在哪里改 | 说明 |
|---|---|---|---|
| 1 | **ADC 引脚约束** | `constraints/scope_dual.xdc` | 新板子的 ADC 接在哪些 pin、什么电平标准 |
| 2 | **ADC 输入时序** | 同上 | `set_input_delay` 的 max/min 要按新板走线重算 |
| 3 | **时钟方案** | BD `scope_adc_clk` | 若新板 ADC 自带时钟 → 用外部时钟；否则沿用 clk_wiz |
| 4 | **AXI 基地址** | BD `assign_bd_address` | 若与别的 IP 冲突要重分配；同时改 `scope_dual.c` 与 `scope_dual.py` |
| 5 | **PS 配置** | BD `processing_system7_0` | DDR/外设按新板；**FCLK_CLK0 = 100 MHz 必须给到 `aclk`** |
| 6 | **fb 分辨率** | `fbui.py` / `apps_scope_dual.py` | `W/H/PLOT/卡片坐标`（见 9.4） |
| 7 | **触摸设备节点** | `fbui.py` `Touch.path` | 新板可能是 `/dev/input/event0` 或别的 |
| 8 | **ADC 前级换算** | `scope_processing.py` | `V_FULL`（当前 10.0 = ±5V）按新前级改 |

### 8.2 完全不用改的（可直接复用）

- `rtl/scope_dual_core.v`（780 行，纯逻辑，与板子无关）
- `rtl/scope_dual_axi.v`（除地址宽度外）
- `ps/scope_dual.c`（除 `BASE`）
- `ps/scope_processing.py` 的算法部分（时基/直方图/分位/标定框架）
- `ps/scope_model.py`（纯状态）
- `apps_scope_dual.py` 的交互逻辑与缓存策略

---

## 九、移植工作流（分步 checklist）

### 阶段 1：环境确认（0.5 天）

- [ ] 新板 FPGA 型号是否**同为 `xc7z020`**（同核心）；封装/速度等级可不同，但要改 `PART`
- [ ] Vivado 版本：本项目用 **2018.3**（IP 已按此版本打包，高版本可能要升级 IP）
- [ ] 新板 Linux 是否可跑 Python3 + PIL；`/dev/fb0` 与触摸设备是否存在

### 阶段 2：PL 侧移植（1~2 天）

```tcl
# 1. 拷贝 IP 仓库
ip_repo/scope_dual_axi/          -> 新工程

# 2. 新 BD 里加时钟
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 scope_adc_clk
#    输入 100MHz（来自 PS FCLK_CLK0）
#    CLKOUT1 = <ADC 需要的时钟>，CLKOUT2 = 同频、相位按 ADC 数据窗口调

# 3. 加示波器 IP 并接线（照抄 3.4 节）
create_bd_cell -type ip -vlnv dsh:user:scope_dual_axi:1.0 scope_dual_0
connect_bd_intf_net  .../Mxx_AXI  scope_dual_0/S_AXI
connect_bd_net FCLK_CLK0          scope_dual_0/aclk
connect_bd_net peripheral_aresetn scope_dual_0/aresetn
connect_bd_net clk_out1           scope_dual_0/adc_ref_clk
connect_bd_net clk_out2           scope_dual_0/sample_clk
connect_bd_net <顶层端口 adc1_data> scope_dual_0/adc1_data
connect_bd_net <顶层端口 adc2_data> scope_dual_0/adc2_data

# 4. 分配地址（记下基地址）
assign_bd_address
```

- [ ] **先跑单模块快速综合**验证 RTL 语法（**30 秒**，不用等 25 分钟全流程）：
      ```tcl
      read_verilog rtl/scope_dual_core.v
      synth_design -top scope_dual_core -part <PART> -mode out_of_context
      report_utilization -file out/core_util.rpt
      ```
      期望：**≈2,839 LUT / 1,045 FF**（偏差过大说明综合选项不对）
- [ ] 写新板的引脚约束（ADC 数据位 + 电平标准）
- [ ] 写 `set_input_delay`（按 ADC 手册的数据有效窗口 + 走线延迟）
- [ ] **若要跨时钟域读包络，务必加那条 `set_max_delay -datapath_only`**（见 3.5）
- [ ] 综合 → 实现 → 确认 `TIMING_MET=1` → 出 bitstream

### 阶段 3：PS 侧移植（0.5 天）

- [ ] 拷 `ps/*.py`、`ps/scope_dual.c` 到新板 `/home/zynq/ui/`
- [ ] 板上编译 C：`gcc -O2 -fPIC -shared -o libscopedual.so scope_dual.c`
- [ ] 改基地址：`scope_dual.c` 的注释 + `scope_dual.py` 的 `DEFAULT_BASE`
- [ ] 按新前级改 `scope_processing.py` 的 `V_FULL`
- [ ] **上板自检**：
      ```
      sudo python3 -c "import sys;sys.path.insert(0,'/home/zynq/ui');import scope_dual as s;d=s.ScopeDual();print(d.hw, hex(d.lib.sd_version()))"
      ```
      期望打印 `True 0x53435034`

### 阶段 4：UI 适配（0.5 天）

- [ ] 改 `fbui.py`：确认 `stride` / `bits_per_pixel` / `mode`（**RGB，别用 BGR**）
- [ ] 改 `Touch.path` 为新板触摸设备
- [ ] 改分辨率与布局（若屏不同）：
      ```
      apps_scope_dual.py:
        W, H        = 屏宽, 屏高
        TOP_H       = 顶栏高度
        PLOT        = [x0, y0, x1, y1]     # 波形区
        CTL_Y, CTL_H= 底部按钮行
        ST1/ST2     = 两行参数区
        cardrect    = 五张卡片的矩形
      ```
- [ ] **上板抓帧对比**（不靠肉眼）：`sudo python3 /tmp/shot_now.py /tmp/s.jpg` 拉回本地看

### 阶段 5：标定（0.5 天，每个通道各做一次）

- [ ] `sudo python3 cal_diag.py rep CH1` → **散差必须 <5%**，否则先查信号/触发
- [ ] **推荐直流法**（能同时定零点和增益）：
      `sudo python3 cal_diag.py dc CH1 0.0 4.0`（依次给 0V 和 4V 直流）
- [ ] 若要修非线性 → 测多点，把点加进 `VPP_CAL` 表
- [ ] `scp` 回本地留档

### 阶段 6：验收（0.5 天）

- [ ] 频率：给已知方波（如 1 kHz），读数误差应 <1%
- [ ] 幅度：给已知 Vpp（如 3.2V），读数误差应 <1%
- [ ] 时基：`50us/div` 时一屏应为 **500 µs**（用 `Timebase(9).actual_tdiv*10` 核对）
- [ ] 帧率 ≥25 FPS、触摸响应 <60 ms、单核 CPU <35%
- [ ] Normal 无触发不阻塞（`sd_capture()` 应 <100 ms）
- [ ] 双通道可同时显示

---

## 十、常见坑速查表

| 现象 | 根因 | 修法 |
|---|---|---|
| **LUT 突然涨到 80%、place 失败** | 包络 BRAM 同拍读-改-写 → 推断不出 BRAM，1008×20 变触发器（+40,320 FF） | **拆成两拍流水** |
| **综合出巨大除法器** | 列号写成 `(idx<<12)/win_len` | 改 **DDA 增量累加**，除数由 PS 算好下发 |
| **`[Synth 8-91] ambiguous clock`** | 含异步复位的块里驱动多个 `output reg` | 该块改**同步复位** |
| **时序违例 −0.229ns** | 包络 BRAM 写 20MHz / 读 100MHz 同源异相 | 加 `set_max_delay -datapath_only` |
| **频率读数乱跳（几 MHz 假值）** | `sd_measure` 用零迟滞中点比较，数出上千假边沿 | 改**施密特迟滞**（pp×12.5%） |
| **低频信号测不出频率** | 只数上升沿；整帧不到 2 个周期 | 改**双向穿越 + 跳变沿估周期** |
| **频率差 25500%** | 系统里有**两张时基表** | 统一到 `scope_processing.TIME_DIV` |
| **时基标签与显示窗口不符** | `draw_wave` 永远画满 4096 点 | 按 `Timebase.span` 切片 |
| **Normal 模式长时间阻塞** | `sd_wait` 的 timeout 参数当循环次数用 | 改**真实微秒超时** + `sd_poll_frame` |
| **FPGA 路径一直不生效** | ①UI 漏了 `sd_start()`（帧采完核停住）②能力检测误用 `valid`（每帧被 `start_pulse` 清零） | 轮询发现空闲补 `start()`；改用**统计点数 n>0** |
| **触发电平线是蓝色** | Python 写 `B,G,R` 而缓冲是 `R,G,B` | 统一走 C 的 `sd_hdash`（写 RGB） |
| **改了数值界面不刷新** | `bump()` 里 commit 完**不重绘** | 加**立刻重绘**受影响区域 |
| **噪声被当成信号** | 小信号阈值 `pp<8` 太松 | 改 `pp<24`（实测空闲 pp≈13 LSB） |
| **V/div 改了波形不变** | 只改了"当前调节通道"，而信号在另一路 | `vdiv_step` 改成**两路一起改** |
| **部署后还是旧界面** | ①桌面未重启（依赖模块没 reload）②应用开着时换文件 | **退出应用重进**；改依赖后**重启桌面**；只 `cp` 文件不要动 systemd |
| **`ptp`/`mmap` 读寄存器全 0** | 地址宽度不够、寄存器被截断 | IP 的 `C_S_AXI_ADDR_WIDTH` 一开始就开到 **12** |
| **串口控制台乱码/炸** | 板上 GBK 控制台，Python 打印 `✓`/`√` | 板上脚本**纯 ASCII** |
| **`pkill -f xxx.py` 把自己也杀了** | 模式匹配到了启动它的 shell | 别用 pkill 自匹配 |

---

## 十一、文件清单（移植时按此拷贝）

```
rtl/
  scope_dual_core.v          580 行  采集引擎（与板子无关，直接复用）
  scope_dual_axi.v           650 行  寄存器接口
ip_repo/scope_dual_axi/              IP 仓库（component.xml + src/）
constraints/scope_dual.xdc   10.9KB 引脚 + 时钟 + 时序约束  ← 必须按新板改
scripts/
  package_scope_dual_ip.tcl          重新打包 IP
  build_scope_dual.tcl               建 BD + 构建
ps/
  scope_dual.c              1061 行  C 驱动/测量 → libscopedual.so
  scope_dual.py              636 行  ctypes 封装
  scope_processing.py        517 行  算法（时基/标定/直方图/包络）
  scope_model.py             289 行  状态模型
  apps_scope_dual.py        1067 行  UI
  fbui.py                     18KB  帧缓冲/触摸框架
  cal_diag.py / cal_scope.py / cal_from_pairs.py   标定工具
  scope_cal.json                     标定结果（自动生成）
```

**验证脚本（可选但强烈建议一起拷）**
```
chk_core2.tcl     30 秒单模块综合 + 资源报告
chk_blocks2.py    Verilog 块结构配平检查
chk_case.py       AXI case 标签重复检查
chk_attrs.py      Python 未定义属性检查
shot_now.py       抓 /dev/fb0 存 JPEG
```

---

## 十二、一句话总结移植要点

> **PL 改 3 样：时钟、引脚约束、BD 接线；PS/UI 改 3 样：AXI 基地址、fb 参数、触摸节点；
> 最后每通道做一次两点标定（推荐直流法）。**
>
> **其余 90% 的代码——从 `scope_dual_core.v` 到 `apps_scope_dual.py`——原样可用。**
