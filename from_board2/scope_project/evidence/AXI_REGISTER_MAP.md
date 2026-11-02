# AXI 寄存器表（阶段8 交付物）

生成时间: 2026-10-10 18:35:15
来源: `rtl/scope_dual_axi.v` 的 localparam（权威）+ `ps/scope_dual.c` 的字节偏移
基地址: `0x43CC0000`  (BD: `assign_bd_address -offset 0x43CC0000 -range 64K`)
地址宽度: IP 内部 `C_S_AXI_ADDR_WIDTH = 12`（字索引 `[11:2]`，可寻址 1024 个字）
字节偏移 = 字索引 x 4

## 控制类（PS 写）

| 字 | 字节 | 寄存器 | 说明 |
|---|---|---|---|
| 0x00 | 0x00 | CTRL | bit0 翻转启动 / bit1 翻转停止 |
| 0x03 | 0x0C | DEC | 抽取倍率（统一时基表算出的 D） |
| 0x05 | 0x14 | TRIGLEV | 触发电平 0..1023 |
| 0x06 | 0x18 | TRIGCFG | bit0 边沿(0升1降) [2:1] 模式 [4:3] 触发源 |
| 0x07 | 0x1C | PRE | 预触发点数 0..4095 |
| 0x09 | 0x24 | RDPTR | 原始帧读指针（逐点读路径用） |
| 0x15 | 0x54 | LOCK | bit0 锁定请求 / bit1 bank / bit2 应答 |
| 0x18 | 0x60 | HYS | 迟滞宽度 LSB |
| 0x19 | 0x64 | ACQMODE | 0=Auto 1=Normal 2=Single 3=Roll |
| 0x1F | 0x7C | TESTPAT | !=0 时用内部测试波形（方波/三角波，周期 2048 点 = 9.765625kHz） |
| 0x29 | 0xA4 | WIN_START | 显示窗口起点（相对触发点，采样点） |
| 0x2A | 0xA8 | WIN_LEN | 显示窗口长度 = Timebase.span |
| 0x2B | 0xAC | COL_STEP | 列号 DDA 步进 = round(1008*65536/win_len)，**PS 算好下发，PL 里没有除法器** |

## 状态 / 描述符类（PS 读）

| 字 | 字节 | 寄存器 | 说明 |
|---|---|---|---|
| 0x0A | 0x28 | RDATA | 原始帧数据（旧路径，每点一次事务） |
| 0x0B | 0x2C | WRTOTAL | 已写入点数 |
| 0x0C | 0x30 | STATUS | 状态位 |
| 0x0D | 0x34 | VERSION | 魔数，SCP4 = 0x53435034 |
| 0x0E | 0x38 | CAPS | 能力位 |
| 0x0F | 0x3C | RATE | 采样率（20 MHz） |
| 0x10 | 0x40 | FRAMESEQ | 帧序号 |
| 0x11 | 0x44 | DESC0 | {bank[12], start_addr[11:0]} |
| 0x12 | 0x48 | DESC1 | sample_count |
| 0x13 | 0x4C | TRIGIDX | 触发点在帧内位置 |
| 0x14 | 0x50 | LOST | 丢帧计数（Bank 未 ACK 时累加） |
| 0x16 | 0x58 | FLAGS | bit0 triggered / bit1 locked / bit2 busy |
| 0x17 | 0x5C | FRAMEDEC | 本帧实际抽取倍率 |
| 0x1A | 0x68 | ROLLPTR | {fill[12:0], roll_ptr[11:0]} |

## 阶段4 新增：列包络读口（**单次读自动递增**）

| 字 | 字节 | 寄存器 | 说明 |
|---|---|---|---|
| 0x04 | 0x10 | ENV_PTR | 写：起始列。bit10=通道(0:CH1 1:CH2)，bit9:0=列号 |
| 0x01 | 0x04 | ENV_DATA | 读：返回该列 {max[9:0], min[9:0]}，**硬件自动 +1**；到第 1007 列自动翻到另一通道 |

**用法**：先写 ENV_PTR = 0，然后连读 1008 次 ENV_DATA 得到 CH1 整条包络，
再连读 1008 次得到 CH2 —— 共 2016 次**单事务**读。
旧路径是「写 RDPTR + 读 RDATA」每点两次事务，4096 点共 8192 次。

## 阶段4 新增：帧统计（**PL 采集时流式算出，PS 只读**）

| 字 | 字节 | 寄存器 | 说明 |
|---|---|---|---|
| 0x20 | 0x80 | ST_MM1 | {max1[9:0], min1[9:0]} |
| 0x21 | 0x84 | ST_MM2 | {max2[9:0], min2[9:0]} |
| 0x22 | 0x88 | ST_SUM1 | 累加和（PS 除以 n 得均值） |
| 0x23 | 0x8C | ST_SUM2 | |
| 0x24 | 0x90 | ST_CLIP1 | {贴1023数, 贴0数} -> 过量程判定 |
| 0x25 | 0x94 | ST_CLIP2 | |
| 0x26 | 0x98 | ST_EDG1 | {首末边沿间隔, 迟滞边沿数} -> PS 一次除法得周期 |
| 0x27 | 0x9C | ST_EDG2 | |
| 0x28 | 0xA0 | ST_N | {valid[15], 统计点数[14:0]} |

## 诊断类（保留，调试用）

| 字 | 字节 | 寄存器 | 说明 |
|---|---|---|---|
| 0x1B | 0x6C | LIVE | 实时 ADC 引脚值 |
| 0x1C | 0x70 | ACT | 数据翻转次数 |
| 0x1D | 0x74 | EVER | 各位是否出现过高/低 |
| 0x1E | 0x78 | CLKCNT | sample_clk 计数（证明时钟树在跑） |

## ⚠️ 已知遗留别名（不影响功能，但读的时候别搞混）

| 地址 | 两个名字 | 说明 |
|---|---|---|
| 0x01 | REG_SOURCE（旧，单通道选源）/ REG_ENV_DATA | ENV_DATA 是从旧 SOURCE 复用的 |
| 0x04 | REG_RESERVED（旧）/ REG_ENV_PTR | ENV_PTR 是从旧 RESERVED 复用的 |
| 0x1C/0x1D | C 侧 `R_STATS1`/`R_EDGE1` 等旧名字 | 对应的其实是 ACT/EVER，**已无人使用** |

**地址重叠检查结论**：0x00..0x2B 全部唯一，**无重叠**（阶段3 bug⑤ 已修复）。
`scope_dual_axi.v` 的两个 `case` 块标签数分别为写 16 / 读 44，均无重复。

