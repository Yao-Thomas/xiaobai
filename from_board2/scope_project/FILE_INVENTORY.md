# 本项目文件清单 —— 路径 × 模块对照

> 工程根目录：`D:\FPGA_project\zynq_scpoe_ds`
> 导出副本：`D:\FPGA_project\zynq_scpoe_ds\scope_export\`
> 生成时间：2026-10-11　器件：`xc7z020clg400-2`

---

## 一、目录总览

```
zynq_scpoe_ds/
├── rtl/                      ★ PL 源码（Verilog）
├── constraints/              ★ 引脚 + 时钟 + 时序约束
├── scripts/                  ★ Vivado 构建/打包/检查脚本
├── sim/                      ★ 仿真 testbench
├── ip_repo/                  ★ 打包好的 IP 仓库
├── ps/                       ★ PS 源码（C + Python）
├── release_candidate/        ★ 交付文档 + 验收证据
├── scope_v4_work/              调试/测量/标定工具
├── vivado/                     Vivado 工程（BD、综合、实现产物）
├── out/                        构建报告（utilization / timing / dcp）
├── baseline_known_good/        已知可用基线备份
├── backup_before_revert/       回退前备份
├── docs/                       文档
└── scope_export/             ← 本次导出的干净副本（54 文件）
```

---

## 二、★ PL 侧（FPGA / Verilog）

| 文件 | 模块 | 职责 | 行数 | 大小 |
|---|---|---|---|---|
| `rtl/scope_dual_core.v` | **采集引擎（核心）** | 抽取 → 双 bank 环形写 → 迟滞触发状态机 → 帧统计引擎 → 列包络引擎 → Bank 锁定/ACK | 580 | 29,194 B |
| `rtl/scope_dual_axi.v` | **寄存器接口** | AXI4-Lite Slave + 寄存器组 + 测试波形发生器 + 诊断计数；内含 `scope_dual_core` 例化 | 650 | 31,403 B |
| `rtl/scope_env.v` | 流式包络（早期版本） | 流式 min/max、迟滞边沿、多周期平均、列包络 BRAM。**已写好，功能已被 core 内的包络引擎取代** | — | 7,324 B |
| `constraints/scope_dual.xdc` | **引脚 + 时序** | ADC 引脚（J4）／`set_input_delay`／包络 CDC 的 `set_max_delay` | — | 10,912 B |
| `constraints/scope_dual.xdc.bak_j3` | 约束备份 | 改动前版本 | — | 7,688 B |
| `sim/tb_scope_dual_core.v` | 仿真 | `scope_dual_core` 的 testbench | — | 3,954 B |

### IP 仓库

| 文件 | 说明 |
|---|---|
| `ip_repo/scope_dual_axi/component.xml` | IP 元数据，VLNV = **`dsh:user:scope_dual_axi:1.0`** |
| `ip_repo/scope_dual_axi/src/scope_dual_axi.v` | 与 `rtl/scope_dual_axi.v` **完全一致**（md5 `d2941f25`）|
| `ip_repo/scope_dual_axi/src/scope_dual_core.v` | 与 `rtl/scope_dual_core.v` **完全一致**（md5 `81497822`）|
| `ip_repo/scope_dual_axi/xgui/scope_dual_axi_v1_0.tcl` | Vivado GUI 定制脚本 |

### 构建脚本

| 文件 | 用途 |
|---|---|
| `scripts/build_scope_dual.tcl` | **主构建脚本**：建 BD、加 `clk_wiz`、例化 IP、接线、分配地址、综合实现、出 bitstream |
| `scripts/package_scope_dual_ip.tcl` | 把 `rtl/` 两个文件**打包成 IP** 放进 `ip_repo/` |
| `scripts/check_adc_post_route.tcl` | 布线后检查 ADC 时钟/时序 |
| `scripts/run_core_sim.tcl` | 跑 `sim/tb_scope_dual_core.v` 仿真 |

---

## 三、★ PS 侧（ARM / Linux）

### 3.1 示波器运行时（**必需**）

| 文件 | 模块 | 职责 | 行数 | 板上位置 |
|---|---|---|---|---|
| `ps/scope_dual.c` | **C 驱动 + 热路径测量** | `/dev/mem` mmap 寄存器；`sd_measure` 帧测量；`sd_hdash`/`sd_vdash` 画线；`sd_draw_env` 画包络。编译成 `libscopedual.so` | 1,061 | `/home/zynq/ui/scope.c`（板上改过名）|
| `ps/scope_dual.py` | **ctypes 封装** | `class ScopeDual`：寄存器读写、帧读取、Bank 握手、能力检测（魔数 `0x53435034`）| 636 | `/home/zynq/ui/` |
| `ps/scope_processing.py` | **算法层** | 时基表 `TIME_DIV`、`Timebase`、`ChannelCal`、`VPP_CAL` 标定、直方图/分位、迟滞边沿、包络 | 517 | `/home/zynq/ui/` |
| `ps/scope_model.py` | **状态模型** | `TriggerModel` / `AcqModel` / `DisplayModel` / `ScopeModel`；`commit()` 原子提交 | 289 | `/home/zynq/ui/` |
| `ps/apps_scope_dual.py` | **UI 应用** | 三档刷新、五项调节、弹层、AUTO、缓存策略 | 1,067 | `/home/zynq/ui/` |
| `ps/fbui.py` | **帧缓冲/触摸框架** | `Screen`（mmap `/dev/fb0`）、`Touch`（支持 `/tmp/ui_tap` 注入）、绘图原语 | — | `/home/zynq/ui/` |
| `ps/desktop.py` | **桌面外壳** | 应用图标列表、`run_app()` 进程内加载应用 | — | `/home/zynq/ui/` |

### 3.2 标定工具（**建议带上**）

| 文件 | 用途 |
|---|---|
| `ps/cal_diag.py` | **主力工具**：`rep` 重复性检查 / `dc` 直流两点标定（零点+增益）/ `pp` Vpp 两点标定 |
| `ps/cal_scope.py` | 交互式两点标定，读**原始 ADC 码**（不会误差累加）|
| `ps/cal_from_pairs.py` | 由「真实值/显示值」两组数直接算 `zero`/`gain` 并写 JSON |
| `ps/build_so.sh` | 板上编译 C：`gcc -O2 -fPIC -shared -o libscopedual.so` |

### 3.3 运行时生成

| 文件 | 说明 |
|---|---|
| `/home/zynq/ui/scope_cal.json` | 标定结果（**不随工程走**，每块板单独标）|
| `/home/zynq/ui/libscopedual.so` | `scope_dual.c` 的编译产物 |

---

## 四、调试 / 测量 / 验收工具

| 文件 | 模块 | 用途 |
|---|---|---|
| `scope_v4_work/shot_now.py` | 抓帧 | 读 `/dev/fb0` → JPEG + 颜色统计判定（"有内容/疑似黑屏"）|
| `scope_v4_work/measure_ui.py` | 离屏测量 | `scr.flush` 打桩 + 触摸注入，测响应/切换耗时 |
| `scope_v4_work/breakdown_ui.py` | 逐函数计时 | 定位 UI 绘制瓶颈 |
| `scope_v4_work/cpu_steady.py` | CPU 测量 | 按真实刷新配比跑 60 s，采 `/proc/self/stat` |
| `scope_v4_work/check_cache.py` | 缓存验证 | 确认缓存没把功能改坏 |
| `scope_v4_work/mem_sample.sh` | 长跑采样 | 内存/线程/句柄，判泄漏 |
| `scope_v4_work/fill_fb.py` | 显存测试 | 填充纯色（验证 fb 通路）|
| `scope_v4_work/chk_cal.py` | 标定自检 | 打印板上实际读到的 `zero`/`gain` |
| `scope_v4_work/check_app.sh` | 应用自检 | 检查导入 + 抓异常 |
| `scope_v4_work/cleanup_boot.sh` | 启动分区清理 | 显式白名单删备份（绝不通配 `rm`）|

---

## 五、交付文档与证据（`release_candidate/`）

| 文件 | 内容 |
|---|---|
| **`SCOPE_PORTING_GUIDE.md`** | ★★ **移植与工程说明（666 行 / 12 章）** —— 本文档的上级文档 |
| `ACCEPTANCE_EVIDENCE.md` | 验收证据汇总（18 KB）|
| `AXI_REGISTER_MAP.md` | **完整寄存器地图** |
| `CNN_RESOURCE_BUDGET.md` | CNN 预留额度 |
| `DEPLOY_AND_ACCEPTANCE.md` | 部署与验收流程 |
| `ui_perf_final.txt` / `ui_breakdown_final.txt` | UI 性能实测数据 |
| `accept_final.txt` / `accept_log_20261010.txt` | 验收日志 |
| `check_panel_evidence.txt` / `overrange_evidence.txt` | 弹层 / 过量程 像素比对证据 |
| `soak_progress.txt` / `soak_memory.txt` | 长跑记录 |
| `MANIFEST.md` / `README.md` | 清单与说明 |

---

## 六、模块依赖关系（谁调谁）

```
                        ┌──────────────────────┐
                        │  desktop.py（桌面）   │
                        └──────────┬───────────┘
                                   │ run_app() 进程内加载
                                   ▼
   ┌────────────────────────────────────────────────────┐
   │  apps_scope_dual.py （UI）                          │
   │   三档刷新：触摸 8ms / 波形 40ms / 文字 150ms        │
   └───┬──────────────┬──────────────┬──────────────────┘
       │              │              │
       ▼              ▼              ▼
  fbui.py      scope_model.py   scope_processing.py
  (帧缓冲/触摸)  (状态模型)       (时基/标定/直方图/包络)
       │              │              │
       │              └──────┬───────┘
       │                     ▼
       │            scope_dual.py （ctypes 封装）
       │                     │  ctypes.CDLL
       │                     ▼
       │            libscopedual.so  ←── scope_dual.c
       │                     │  /dev/mem mmap
       │                     ▼
       │            AXI4-Lite @ 0x43CC0000
       │                     │
       │                     ▼
       │            scope_dual_axi.v （寄存器组）
       │                     │
       │                     ▼
       │            scope_dual_core.v （采集引擎）
       │                     ▲
       └─────────────────────┘  adc1_data[9:0] / adc2_data[9:0]（引脚）
```

**★ 分层纪律**：
- **UI 不许直接写硬件寄存器** → 一律经 `ScopeModel.commit(hw)`
- **PS 不做逐点/逐像素运算** → 热路径全在 `scope_dual.c` 或 PL
- **`scope_processing.TIME_DIV` 是全系统唯一时基表**

---

## 七、移植时"必带 / 可选"

### ★ 必带（少一个都跑不起来）

```
rtl/scope_dual_core.v
rtl/scope_dual_axi.v
constraints/scope_dual.xdc              ← 必须按新板改
scripts/package_scope_dual_ip.tcl
scripts/build_scope_dual.tcl
ip_repo/scope_dual_axi/                 ← 或由上面脚本重新生成
ps/scope_dual.c
ps/scope_dual.py
ps/scope_processing.py
ps/scope_model.py
ps/apps_scope_dual.py
ps/fbui.py
ps/desktop.py
ps/build_so.sh
```

### ○ 建议带

```
sim/tb_scope_dual_core.v                仿真回归
ps/cal_diag.py / cal_scope.py / cal_from_pairs.py    标定
scope_v4_work/shot_now.py               上板抓帧
scope_v4_work/chk_cal.py                标定自检
scope_v4_work/measure_ui.py             性能测量
release_candidate/*.md                  文档与证据
```

### ✗ 不必带

```
vivado/             Vivado 工程产物（在新机器上重新生成）
out/                构建报告（重新生成）
*.log / *.backup.log
_inspect* / _ballproj / _package_project / _sim_project / _lcd_hls_test
baseline_known_good / backup_before_revert        历史备份
__pycache__/
```

---

## 八、导出副本的实际内容

`D:\FPGA_project\zynq_scpoe_ds\scope_export\`（**54 文件 / 554.5 KB**）

```
scope_export/
├── MANIFEST.csv                54 条：路径 / 字节数 / MD5
├── rtl/            3 文件   67,921 B   scope_dual_core.v  scope_dual_axi.v  scope_env.v
├── constraints/    1 文件   10,912 B   scope_dual.xdc
├── scripts/       14 文件   39,264 B   构建 tcl + 测量/标定工具 + build_so.sh
├── sim/            1 文件    3,954 B   tb_scope_dual_core.v
├── ip_repo/
│   └── scope_dual_axi/          component.xml + src/(2) + xgui/(1)
├── ps/            11 文件  230,506 B   运行时 + 标定工具
├── docs/           2 文件   17,378 B   AGENTS.md  SCOPE_DUAL_DEPLOY.md
└── evidence/      18 文件   95,960 B   release_candidate/ 全部内容
```

### 关键文件哈希（前 8 位）

| 文件 | MD5 前缀 | 说明 |
|---|---|---|
| `ps/apps_scope_dual.py` | `b1dffcf7` | **与板端部署版本一致** ✓ |
| `ps/scope_processing.py` | `8ee42ccd` | **与板端部署版本一致** ✓（含 `VPP_CAL`）|
| `ps/scope_model.py` | `07788e94` | **与板端部署版本一致** ✓ |
| `ps/scope_dual.py` | `bc0fc706` | |
| `ps/scope_dual.c` | `e6e6a293` | 板上叫 `scope.c` |
| `rtl/scope_dual_core.v` | `81497822` | 与 `ip_repo` 内一致 ✓ |
| `rtl/scope_dual_axi.v` | `d2941f25` | 与 `ip_repo` 内一致 ✓ |
| `constraints/scope_dual.xdc` | `d3e834c6` | |

---

## 九、板上对应位置（部署映射）

| 本工程 | 板端路径 |
|---|---|
| `ps/scope_dual.c` | `/home/zynq/ui/scope.c`（**改名**）|
| `ps/*.py` | `/home/zynq/ui/*.py` |
| `ps/libscopedual.so`（编译产物）| `/home/zynq/ui/libscopedual.so` |
| 配置标记 | `/home/zynq/ui/.scope_addr`（内容 `0x43CC0000`）|
| 标定结果 | `/home/zynq/ui/scope_cal.json`（运行时生成）|
| bitstream | `/mnt/boot/system.bit` |

**部署命令（不改动操作系统）**
```bash
sudo cp /tmp/xxx.py /home/zynq/ui/ && sudo rm -rf /home/zynq/ui/__pycache__
```
> ★ 桌面只在**点图标进应用**时 `importlib.reload` 应用模块，
> **不会 reload 依赖模块**（`scope_model` / `scope_processing`）→ 改这些要**重启桌面**。

---

## 十、一句话索引

| 想改什么 | 去哪 |
|---|---|
| 采样/触发/抽取/包络逻辑 | `rtl/scope_dual_core.v` |
| 加寄存器 / 改寄存器地址 | `rtl/scope_dual_axi.v` |
| 换板子引脚 / 电平标准 | `constraints/scope_dual.xdc` |
| 时基档位 / 电压标定 / 测量算法 | `ps/scope_processing.py` |
| 寄存器读写 / 帧搬运 | `ps/scope_dual.py`、`ps/scope_dual.c` |
| 通道/触发/采集 状态与互斥 | `ps/scope_model.py` |
| 界面布局 / 刷新 / 缓存 | `ps/apps_scope_dual.py` |
| 屏幕 / 触摸底层 | `ps/fbui.py` |
| Vivado 工程结构 | `scripts/build_scope_dual.tcl` |
