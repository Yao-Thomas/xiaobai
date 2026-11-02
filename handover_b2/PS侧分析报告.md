# PS 侧分析报告 —— 他的双通道示波器 → 我们板子（192.168.10.20）

> 作者：board-analyst
> 日期：2026-10-15
> 素材：`D:\ubuntu_iso\from_board2\scope_project\ps\`（他的工程包，权威）+ `D:\ubuntu_iso\from_board2\ui\`（他板上下载）+ **我们板子 192.168.10.20 只读实测**
> 交叉参考：`_baseline\20261014\notes\移植影响评估.md`、`移植方案_v1.md`、`from_board2\scope_project\docs\SCOPE_DUAL_DEPLOY.md`
> **本篇所有板端结论均为只读实测；本次任务未对板子写入任何文件。**

---

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| 能不能照搬他的 PS 层 | **能，85% 可原样搬**。只有 4 处必须改 |
| ★ 必须改的第 1 处 | **他的 `scope_dual.py` 和我们 `scope.py` 读同一个标记文件 `/home/zynq/.scope_addr`** —— 不改就会两个示波器抢同一个地址 |
| 必须改的第 2 处 | `scope_dual.py` 的 `DEFAULT_BASE`（0x43CC0000 → 建议 0x43D00000） |
| 必须改的第 3 处 | `desktop.py` 加入口（我们不用他的 desktop.py，见 §7） |
| 必须改的第 4 处 | 版本魔数一致性：**包里的 RTL 是 SCP3（0x53435033），但 RTL 的注册表文档写 SCP4** —— 必须由 vivado-builder 拍板 |
| `fbui.py` 能不能用他的 | **绝对不能**。见 §7，他包里那份还是残留的旧版，连他自己的 `apps_scope_dual.py` 都跑不起来 |
| `desktop.py` 能不能用他的 | **绝对不能**。他的 51KB 里没有我们 26 个 App 中的 12 个 |
| 分辨率 / 触摸节点 | **不用改**。我们也是 1024x600，`find_touch()` 两边逐字节相同 |
| CNN 链路 | 见 §8。现在**和示波器是解耦的**；把他的示波器搬到新地址 ⇒ CNN 链路**一行都不用改** |

---

## 1. 三层架构与文件清单

```
UI 层    apps_scope_dual.py   48922 B   1067 行   三档刷新 / 五项调节 / 弹层 / AUTO
   ↓
模型层  scope_model.py        10865 B    289 行   TriggerModel/AcqModel/DisplayModel；commit() 原子提交
   ↓
算法层  scope_processing.py   19066 B    517 行   TIME_DIV 统一时基表 / ChannelCal 两点标定 / VPP_CAL 分段线性
   ↓
封装层  scope_dual.py         26506 B    636 行   ctypes 封装 libscopedual.so；寄存器读写 + 帧缓存 + 窗口下发
   ↓
C 热路径 scope_dual.c         42737 B   1061 行   /dev/mem mmap；sd_measure 帧测量；sd_envelope 列包络；sd_draw_env 上色
   ↓ 板上 gcc 编译
       libscopedual.so         24244 B           板上编译产物（不可跨内核/工具链直接复用，必须板上重编）
════════════ AXI4-Lite @ 0x43CC0000 (64K) ════════════
PL      scope_dual_axi.v     31403 B            AXI4-Lite 从机 + 寄存器组 + 测试波形 + 诊断计数
PL      scope_dual_core.v    29194 B            抽取→双bank环形写→迟滞触发→帧统计→列包络→Bank锁定
PL      scope_env.v           7324 B            ★ 独立包络模块（cores 里那份是内联版，见 §6）
```

**设计原则（他 AGENTS.md 原话，值得继承）：逐点 / 逐像素的运算一律放 PL，PS 只做寄存器读写、帧搬运、UI 绘制与常数级换算。**

反例数据（他实测）：4096 点逐点扫描 → Python **0 FPS** / C **17 FPS** / PL **60 FPS** 量级。

### 1.1 ★ 工程包 vs 他板上的文件差异（重要）

| 文件 | 工程包 | 他板上 `/home/zynq/ui/` | 用什么 |
|---|---|---|---|
| `scope_dual.c` | **42737 B（1061 行，完整）** | 9806 B（删减版，叫 `scope.c`） | ★ **用工程包那份** |
| `scope_dual.py` | 26506 B | 26506 B | 同 |
| `scope_processing.py` | 19066 B | 19066 B | 同 |
| `scope_model.py` | 10865 B | 10865 B | 同 |
| `apps_scope_dual.py` | 48922 B | 48922 B | 同 |
| `libscopedual.so` | 包里没有 | 24244 B | ★ **板上重新编译**，不要传他编译好的 |
| `fbui.py` | 18105 B | **他板上没下载到** | ★ **用我们的**（见 §7） |
| `desktop.py` | 51025 B | **他板上没下载到** | ★ **用我们的**（见 §7） |

> 他板上的 `scope.c`（9806 B）和我们板上的 `scope.c`（9806 B）**同名同大小但无关**：我们那份是单通道示波器的 C，他那份是双通道的删减版。别搞混。

---

## 2. `scope_dual.c`（C 热路径）逐项分析

文件：`from_board2\scope_project\ps\scope_dual.c`（42737 B / 1061 行）

### 2.1 mmap 了哪些寄存器

```c
/* scope_dual.c:27,86-106 */
#define MAP_SIZE 0x10000                 // 64 KB，正好一个 AXI-Lite 槽
static volatile uint32_t *REG = 0;
static int MEMFD = -1;
static unsigned int G_BASE = 0;

int sd_open(unsigned int base) {
    if (REG) return 0;
    MEMFD = open("/dev/mem", O_RDWR | O_SYNC);          // ★ O_SYNC = 不可缓存、强序
    if (MEMFD < 0) return -1;
    m = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, MEMFD, (off_t)base);
    ...
    REG = (volatile uint32_t *)m;  G_BASE = base;
}
```

**要点**
- **唯一的 mmap 就是这一处**，64 KB，基址由参数传入（**代码里没有硬编码基址**）⇒ 换地址只需改 Python 侧一行。
- `O_SYNC` 是必要的（绕过 D-cache，否则读回的是缓存旧值），代价是**每次访问都是一次真实 AXI 事务，约 100~200 ns**。这一点直接决定了 §6 的 CPU 账。
- 访问宏：`sd_rd(off) = REG[off/4]`、`sd_wr(off,v) = REG[off/4] = v`（`scope_dual.c:120-121`）。

### 2.2 它依赖的全部 AXI 寄存器（字节偏移）

**控制类（PS 写）**

| 偏移 | 宏名 | 说明 |
|---|---|---|
| 0x00 | `R_CTRL` | bit0 翻转启动 / bit1 翻转停止 |
| 0x04 | `R_SOURCE` / **`R_ENV_DATA`** | 旧单通道选源；阶段4 复用为**包络读口** |
| 0x08 | `R_DIV` | 分频 |
| 0x0C | `R_DEC` | 抽取倍率 |
| 0x10 | `R_RESERVED` / **`R_ENV_PTR`** | 旧保留；阶段4 复用为**包络写起始列**（bit10=通道） |
| 0x14 | `R_TRIGLEV` | 触发电平 0..1023 |
| 0x18 | `R_TRIGCFG` | bit0 边沿 / [2:1] 模式 / [4:3] 触发源 |
| 0x1C | `R_PRE` | 预触发点数 |
| 0x24 | `R_RDPTR` | 原始帧读指针 |
| 0x54 | `R_LOCK` | bit0 锁定请求 / bit1 bank / bit2 应答 |
| 0x60 | `R_HYS` | 迟滞宽度 |
| 0x64 | `R_ACQMODE` | 0=Auto 1=Normal 2=Single 3=Roll |
| 0x7C | `R_EDGE2` / `TESTPAT` | 旧别名；阶段4 作 TESTPAT 内部测试波形 |
| 0xA4 | `R_WIN_START` | 显示窗口起点 |
| 0xA8 | `R_WIN_LEN` | 显示窗口长度 |
| 0xAC | `R_COL_STEP` | ★ 列号 DDA 步进 = `round(1008*65536/win_len)`，**PS 算好下发** |

**状态类（PS 读）**

| 偏移 | 宏名 | 说明 |
|---|---|---|
| 0x28 | `R_RDATA` | 原始帧数据（硬件自动 +1） |
| 0x2C | `R_WRTOTAL` | 已写入点数 |
| 0x30 | `R_STATUS` | 状态位 |
| 0x34 | `R_VERSION` | 魔数 |
| 0x38 / 0x3C | `R_CAPS` / `R_RATE` | 能力位 / 采样率 |
| 0x40 | `R_FRAMESEQ` | 帧序号 |
| 0x44 / 0x48 | `R_DESC0` / `R_DESC1` | `{bank, start_addr}` / `sample_count` |
| 0x4C | `R_TRIGIDX` | 触发点在帧内位置 |
| 0x50 | `R_LOST` | 丢帧计数 |
| 0x58 | `R_FLAGS` | bit0 triggered / bit1 locked / bit2 busy |
| 0x5C | `R_FRAMEDEC` | 本帧实际抽取倍率 |
| 0x68 | `R_ROLLPTR` | `{fill[12:0], roll_ptr[11:0]}` |
| 0x80~0xA0 | `R_ST_MM1/2, ST_SUM1/2, ST_CLIP1/2, ST_EDG1/2, ST_N` | ★ 阶段4 **帧统计**（PL 流式算，PS 只读 9 个寄存器） |

**⚠️ 已知别名（别读错）**：0x04 是 `R_SOURCE`/`R_ENV_DATA`；0x10 是 `R_RESERVED`/`R_ENV_PTR`；0x70/0x74/0x78/0x7C 的 `R_STATS1/2`、`R_EDGE1/2` 是**旧名字**，实际落到 `ACT/EVER`、`TESTPAT`，**C 里已无人使用**。

### 2.3 热路径 `sd_measure` 到底做了什么

`scope_dual.c:590-733`，**每次调用对 4096 点做一遍，前面还有 1024 桶直方图**：

1. **1024 桶直方图**（`hist[1024]`，清零 + 遍历 n 点各 +1）—— `:601-605`
2. **1% / 99% 分位**（累计到阈值即取，两趟最多 2048 次比较）—— `:607-619`
   - ★ 这是**稳健极值**，故意不用原始 min/max，避免孤立毛刺拉偏
3. **迟滞门限**：`mid = (p1+p99)/2`；`hys = (p99-p1)/8` 夹在 `[3, 200]` —— `:621-626`
4. **迟滞（施密特）穿越计数**：`armed_lo` 状态机，上升沿 + 下降沿都算 —— `:638-655`
   - 注释解释得很清楚：只数上升沿需要 ≥2 个上升沿才能算周期，单周期信号永远测不出来
5. **周期估计双路**：
   - **跳变法**（主）：相邻两点跳变 > 稳健峰峰/2 视为回扫沿，取相邻回扫间隔的**中位数**；若跳变符号正负交替（方波）再 ×2 —— `:672-706`
   - **穿越法**（备）：穿越间隔的插入排序取 `gaps[ng-1]`，再 ×2 —— `:709-718`
6. 输出 7 个 int：`out[0]=p1(Vmin) out[1]=p99(Vmax) out[2]=mid out[3]=edges out[4]=周期点数 out[5]=高于中点的点数 out[6]=n`

**成本量级**：直方图 4096 次 + 两趟 1024 次 + 一趟 4096 次 + 两处最多 512 元素的**插入排序**（O(n²)，最坏 512²/2 ≈ 13 万次比较）。这是**每帧、每通道**跑，即每帧 2 次。

### 2.4 其他 C 热函数

| 函数 | 行 | 做什么 | 成本关键点 |
|---|---|---|---|
| `sd_read_raw` | 385-400 | 写一次 `RDPTR`，再连读 `RDATA` n 次（硬件自动 +1） | ★ 好路径：**n+1 次事务**；注释特意加了 `(void)REG[...]` 吸收一次往返让预取跟上 |
| `sd_read_ch` | 403-419 | 同上 + 拆两通道（`&0x3FF` / `>>16 &0x3FF`） | malloc + 多一趟拷贝 |
| `sd_read_frame_locked` | 437-502 | **锁 bank → 读 DESC0/DESC1 → 搬数据 → 发 ACK** | ★ 正确性核心：ACK 之前核不覆盖该 bank，所以拿到的是同一个不可变帧 |
| `sd_read_envelope` | 223-240 | ★ 阶段4 快路径：写 `ENV_PTR=0`，然后 **连读 `ENV_DATA` 2×cols 次**（硬件每次自动 +1，第 1007 列自动翻另一通道） | **2×1008 = 2016 次单事务读**，对比旧路径 8192 次 |
| `sd_set_window` | 187-198 | 下发 `WIN_START/WIN_LEN/COL_STEP`；`step = (1008ULL*65536)/len` | ★ **除法放在 PS**，PL 只做增量累加，避免综合出除法器 |
| `sd_envelope` | 938-963 | C 里做**列包络**（每列取该列覆盖采样区间的 min/max） | 逐列内层循环，总迭代 = n；在 C 里比 Python 快两个数量级 |
| `sd_draw_env` | 973-1004 | 把 `{min,max}` 映射成像素并画竖线（`p[0]=cr;p[1]=cg;p[2]=cb`，**RGB**） | 逐像素写，总写量 ≈ 波形像素数 |
| `sd_hdash` / `sd_vdash` | 1044+ / 741 | 横/竖虚线，自带 2 像素粗 | 替代 Python 双层循环（原 504 次迭代 ≈ 4.5 ms） |
| `sd_saturation` | 911-925 | 过载检测：`<=4` / `>=1019` 计数 + 最长连续段；判据 `(nlo+nhi) >= n/64` 或任一连续段 ≥16 | 一趟 O(n) |
| `sd_measure_ex` | 770-886 | 更重的稳健测量版本（rise/fall/events/gaps 四组 512~1024 元素数组） | 双路，比 `sd_measure` 更贵 |

### 2.5 ★ 版本魔数：包里的 RTL 和他文档说的**不一致**

| 来源 | 值 | 说明 |
|---|---|---|
| `scope_dual.c:81-82` | `VERSION_MAGIC = 0x53435032 ("SCP2")` / `VERSION_MAGIC_3 = 0x53435033 ("SCP3")` | `sd_probe()` **只认这两个** |
| `scope_dual.c:279-285` | `return (v == VERSION_MAGIC \|\| v == VERSION_MAGIC_3) ? 1 : 0;` | ★ 只认 SCP2 / SCP3 |
| **`rtl/scope_dual_axi.v:610`（权威）** | `s_axi_rdata <= 32'h53435033;  // "SCP3"` | **包里 RTL 实际发的是 SCP3** |
| `evidence/AXI_REGISTER_MAP.md:34` | 「魔数，SCP4 = 0x53435034」 | ★ **和他自己的 RTL 矛盾** |
| `scope_dual.py:492` | `if not self.hw or int(self.lib.sd_version()) < 0x53435034:` | ★ `pl_frame_stats()` 要求 **≥ SCP4**，用包里 RTL 永远进不去 |
| 我们板子当前（实测） | `0x43CC0034 = 0x53434F50 ("SCOP")` | 我们的 `scope_cap_axi` |

**⇒ 三个后果**
1. 移植影响评估里「工程包寄存器表 = SCP4 最新」的说法，**只来自他的文档，RTL 源码并不支持**。以 RTL 为准 ⇒ **包里是 SCP3**。
2. `sd_probe()` 只认 SCP2/SCP3 ⇒ 只要 vivado-builder 出来的流魔数是 SCP3（或改成 SCP2），**C 不用改**。
3. **如果 vivado-builder 为了「看起来更新」把魔数改成 SCP4，`sd_probe()` 会失败 ⇒ `ScopeDual.hw=False` ⇒ 整个应用静默退回没有硬件的状态。** 这是最容易翻车的一处，务必锁死。
4. `pl_frame_stats()`（`scope_dual.py:490-503`）用包里 RTL 恒不可用。但 `apps_scope_dual.py` 走的是 `sd_read_stats()`，**不受影响**，可以放着不管。

---

## 3. `scope_dual.py`（ctypes 封装）逐项分析

文件：`from_board2\scope_project\ps\scope_dual.py`（26506 B / 636 行）

### 3.1 ★★ 基地址写在哪 —— 这是移植的第一号坑

```python
/* scope_dual.py:24-29 */
HERE   = os.path.dirname(os.path.abspath(__file__))     # == /home/zynq/ui
LIB    = os.path.join(HERE, "libscopedual.so")          # 同目录找 .so
MARKER = "/home/zynq/.scope_addr"                       # ★★ 和我们的 scope.py 同一个文件
DEFAULT_BASE = 0x43CC0000
```

```python
/* scope_dual.py:62-84 */
def __init__(self, base=None, verbose=True):
    self.base = DEFAULT_BASE
    if base is None:
        try:
            base = int(open(MARKER).read().strip(), 0)   # ★ 标记文件优先于 DEFAULT_BASE
        except Exception:
            base = None
    if base is None:
        self.why = "缺 %s（bitstream 里没有双通道采集器？）" % MARKER
    ...
    r = lib.sd_open(ctypes.c_uint(base))                 # :157
```

**我们板子实测**：
```
$ ls -la /home/zynq/.scope_addr
-rw-r--r-- 1 zynq zynq 11 Sep 26 13:53 /home/zynq/.scope_addr
$ cat /home/zynq/.scope_addr
0x43CC0000
```
我们的 `/home/zynq/ui/scope.py:19,68,73` **也读同一个 `MARKER`**：

```python
/* 我们的 scope.py */
19: MARKER = "/home/zynq/.scope_addr"
68:     base = int(open(MARKER).read().strip(), 0)
73:     self.why = "缺 %s (bitstream 里没有采集器?)" % MARKER
```

**⇒ 结论（必须写进部署检查单）**
- 只改 `DEFAULT_BASE` **不够**，因为 `MARKER` 会覆盖它。
- 只改 `/home/zynq/.scope_addr` **是灾难**，那会把我们的单通道示波器一起改到新地址。
- **正确做法**：给双通道用**独立的标记文件**，别碰 `.scope_addr`：
  ```python
  # 移植补丁（推荐）
  MARKER = "/home/zynq/.scope_dual_addr"
  DEFAULT_BASE = 0x43D00000        # 与 A1 方案一致；由 vivado-builder 最终确认
  ```
  并新增文件 `/home/zynq/.scope_dual_addr` 内容 `0x43D00000`。
  这样我们的 `scope.py` 继续读 `.scope_addr = 0x43CC0000`（SCOP 不动），他的读 `.scope_dual_addr = 0x43D00000`，**两个示波器彻底解耦**。

### 3.2 魔数怎么校验

```python
/* scope_dual.py:155-171 */
r = lib.sd_open(ctypes.c_uint(base))
...
elif not lib.sd_probe():                 # ★ C 侧判 SCP2 / SCP3
    got = lib.sd_version()
    self.why = ("0x%08X 读到的 VERSION=0x%08X，不是 SCP2"
                "（bitstream 没加载？还是老的单通道版？）" % (base, got))
```

两级校验：
1. `os.path.exists(LIB)` —— 没有 `.so` 直接报「没有 libscopedual.so」
2. `lib.sd_probe()` —— 读 0x34，**只接受 0x53435032 / 0x53435033**

失败时 `self.hw = False`，**不抛异常**，应用会静默降级。所以部署后**必须显式跑一次 `sd_version_str()` 打印确认**，否则会以为「跑起来了」其实一直没硬件。

### 3.3 帧读取流程（两条路径）

**路径 A —— 阶段4 快路径（`apps_scope_dual` 首选，但当前被关掉，见 §6）**
```
sd_poll_frame()  ── 非阻塞，没就绪立刻返回 0（绝不 sleep 等帧）
  → sd_read_stats(stout[16])          9 个寄存器，PL 流式算好的
  → stout[14] == 0 ? 再等一轮 : 继续
  → sd_read_envelope(env1min, env1max, env2min, env2max, 1008)
        写 ENV_PTR=0 → 连读 ENV_DATA 2016 次（硬件自动 +1，到 1007 翻通道）
  → _stat_to_meas() 把统计寄存器变成 UI 用的 dict（几次除法，零循环）
```

**路径 B —— C 回退路径（当前实际在跑）**
```
sd_poll_frame() → sd_busy()!=1 则补一次 sd_start()
  → sd_read_frame_locked(buf1, buf2, 4096, info[8])
        锁 bank → 读 DESC → 搬 4096 点 → 发 ACK
  → sd_measure(buf1) / sd_measure(buf2)      直方图 + 分位 + 迟滞 + 排序
  → sd_saturation(buf1) / sd_saturation(buf2)
  → _to_meas() 整理
```

**帧描述符 info 布局**（`scope_dual.c:424-431`）：`[0]=seq [1]=bank [2]=start_addr [3]=sample_count [4]=trig_index [5]=lost [6]=frame_decimation [7]=triggered`

### 3.4 `TIMEBASES` 表（旧表，注意和新表并存）

```python
/* scope_dual.py:29-40 —— (DIV, DEC, 标签)，DIV 恒为 5 */
TIMEBASES = [(5,1,"50ns/点"), (5,2,"100ns/点"), (5,5,"250ns/点"), (5,10,"500ns/点"),
             (5,20,"1us/点"), (5,50,"2.5us/点"), (5,100,"5us/点"), (5,200,"10us/点"),
             (5,250,"12.5us/点"), (5,254,"12.7us/点")]
```
- `FCLK_HZ = 100e6`（PL 递给 ADC 时钟模块），`ADC_FS_HZ = 20e6`。
- ★ **这张表和 `scope_processing.TIME_DIV` 是两张表**。他 `ACCEPTANCE_EVIDENCE.md:81` 自己记录过：「时基表有两张 -> 频率误差 25500%（统一成一张后 0.00%）」。**移植时以 `scope_processing.TIME_DIV` 为唯一权威**，`TIMEBASES` 只保留给 `scope.py` 兼容路径用。

---

## 4. `scope_processing.py`（算法层）

文件：19066 B / 517 行

### 4.1 ★ `TIME_DIV` 完整 16 档（统一时基表，全系统唯一权威）

```python
/* scope_processing.py:68-72 —— 每格时间（秒），10 格 = 一屏 */
TIME_DIV = [ 50e-9, 100e-9, 200e-9, 500e-9,
             1e-6,  2e-6,   5e-6,   10e-6, 20e-6, 50e-6,
             100e-6, 200e-6, 500e-6, 1e-3, 2e-3, 5e-3 ]
```
即：**50ns / 100ns / 200ns / 500ns / 1us / 2us / 5us / 10us / 20us / 50us / 100us / 200us / 500us / 1ms / 2ms / 5ms 每格**。

### 4.2 `Timebase` 的换算（关键，不能改）

```python
window = req_tdiv * 10.0                      # 一屏要覆盖的时间
target = FS_HZ * window / DEPTH               # 想要的总抽取比
dec    = max(1, min(65535, ceil(target)))     # D
span   = round(FS_HZ * window / dec)          # 该窗口内实际采样点数
actual_tdiv = span * dec / FS_HZ / 10.0       # ★ 横轴必须显示这个，不是 req_tdiv
dt     = dec / FS_HZ                          # 帧内相邻两点时间
err    = |actual_tdiv - req_tdiv| / req_tdiv
```
- `DEPTH = 4096`、`FS_HZ = 20e6`。
- `dec_register()` 返回 `self.dec`（硬件把抽取实现为 div×dec，这里统一按 dec 下发）。
- **横轴误差实测全 16 档 0.010%**（`ACCEPTANCE_EVIDENCE.md:72`）。移植后必须复测这个数。

### 4.3 ★ `VPP_CAL` 怎么用（分段线性反解）

```python
/* scope_processing.py:162-168 —— (真实 Vpp, 名义显示 Vpp) */
VPP_CAL = [ (0.00, 0.00), (1.01, 1.00), (4.29, 4.00),
            (6.46, 6.00), (7.57, 7.00) ]
```
用户给的实测（真实 → 名义）：`1.00→1.01  4.00→4.29  6.00→6.46  7.00→7.57`。
比值 `1.010 / 1.073 / 1.077 / 1.081` **不是常数 ⇒ 不是纯比例误差**，所以不能用「乘一个系数」修（试过 `V_CAL`，被用户否掉）。改用**分段线性插值反解**，等价于带截距的直线 `f(x) = 1.09333x - 0.08333`，最大偏差 0.25%。

`vpp_correct(v)`：按绝对值查表，落在哪段就在哪段线性插值；超出表尾按末段斜率**外推**；保留符号。

**用法链**：`sd_measure` 给的是**未标定的原始 ADC 码** → `ChannelCal` 用两点标定（zero / gain）转成电压 → Vpp 再过 `vpp_correct()`。注释特别强调：**因为标定工具读的是原始码，反复标定永远不会误差累加**（手抄屏幕显示值就会）。

### 4.4 `ChannelCal`（每通道两点标定）

概念：`V = (lsb - zero) * (V_FULL / SAMPLE_MAX) * gain`，令 `K = V_FULL/SAMPLE_MAX`，则 `V = (lsb-zero)*K*gain`。
两点 `(lsb1,V1) (lsb2,V2)` 解出 `B = (V2-V1)/(lsb2-lsb1)`，`zero = lsb1 - V1/B`，`gain = B/K`。
配套工具 `cal_scope.py`（交互或 `cal_scope.py 1.0 4.0`）、`cal_diag.py`、`cal_from_pairs.py`。

**常量**（移植时要核对）：`V_FULL`（当前 10.0 = ±5V，3PA1030 前级 `VO = VI/5 + 1`）、`SAMPLE_MAX = 1023`、`MID`、`DEPTH = 4096`、`CAL_ZERO`、`CAL_GAIN`。

---

## 5. `scope_model.py`（模型层）

文件：10865 B / 289 行。四个模型：`TriggerModel` / `AcqModel` / `DisplayModel` / `ScopeModel`。

### 5.1 ★ `commit()` 的原子提交语义

```python
/* scope_model.py:270-282 */
def commit(self, hw):
    """把当前配置一次写给 PL。UI 不该自己碰硬件寄存器。"""
    hw.configure(timebase=self.tb_index)
    hw.set_dec(self.tb.dec)
    hw.set_acqmode(self.acq.mode)
    hys = self.auto_hys()
    if self.trig.auto_hys:
        self.trig.hys = hys
    hw.set_hys(self.trig.hys)
    hw.set_trigcfg(self.trig.edge, self.acq.mode, self.trig.src)
    hw.configure(triglev=self.trig.level, pre=int(self.trig.pretrigger * 4096))
    self._dirty = False
```

**语义要点**
- **UI 只改 `ScopeModel` 的字段，从不直接碰寄存器**；改完调一次 `commit(hw)` 把整套配置一次下发。这就是「原子提交」：**不会出现「时基已经换了、抽取倍率还是旧的」这种中间态**。
- `_dirty` 标志 + `mark_dirty()` + `dirty` 属性：UI 改参数时置脏，只在脏的时候或关键动作（AUTO/模式切换/弹层确定）才 `commit`。
- `commit` 内部**有顺序依赖**：先 `set_dec` 再 `set_acqmode` 再 `set_hys` 最后 `set_trigcfg`。移植时不要重排。
- 注意 `pre=int(self.trig.pretrigger * 4096)` —— `pretrigger` 是**比例 (0..1)**，乘 4096 变点数。他默认 `pretrigger = 0.5` ⇒ **2048**，正好等于 RTL 的 `reg_pretrigger` 默认值（见 §6，这个 2048 是 95 列 bug 的一半原因）。

### 5.2 其他语义

| 方法 | 语义 |
|---|---|
| `toggle_display(i)` | **只改显示**，绝不改触发源、不改当前调节通道（三者独立） |
| `set_active(i)` | 切换当前调节通道 |
| `set_trig_src(s)` | 触发源独立于显示 |
| `set_timebase(idx)` / `tb_step(d)` | 改时基索引，重建 `Timebase` |
| `vdiv_step` / `vpos_step` / `level_step` / `hpos_step` | 五项调节的加减，带边界夹取 |
| `auto_range(m, grid_r=8)` | AUTO：定 3 周期时基 + 75% 幅度量程 + 水平位置归零 |
| 默认值 | `tb_index = 11`（**200us/格**，一屏 2ms）；`ch[0].enabled = True`、`ch[1].enabled = True`（默认两路都显示） |

> `tb_index = 11` 是特意改的：原来默认 1us/格（一屏 10us），而 1kHz 信号周期 1ms ⇒ 一屏连 1% 个周期都不到，频率永远测不出来（读数是把信号自身缓慢漂移当穿越，显示 4~8kHz 假值）。

---

## 6. `apps_scope_dual.py`（UI 层）

文件：48922 B / 1067 行

### 6.1 三档刷新怎么实现

```python
/* apps_scope_dual.py:64-66 */
TOUCH_DT = 0.008      # 125 Hz
WAVE_DT  = 0.040      # 25 FPS（规范 25~30；draw_wave 是最大单项，取低速端）
TEXT_DT  = 0.150      # 6.7 FPS
```

```python
/* apps_scope_dual.py:1029-1067 —— 单线程主循环 */
while True:
    ev = touch.poll(move=True)            # ① 触摸优先，每轮无条件轮询一次
    if ev: app.handle(x, y, kind)
    now = time.time()
    app.step()                            # ② 采集（非阻塞，绝不 sleep 等帧）
    ...AUTO 逻辑（自动跑一次，最多 400 轮）...
    if app.panel is None:
        if now - app.last_wave >= WAVE_DT:  # ③ 波形档
            app.draw_wave(); app.last_wave = now
        if now - app.last_text >= TEXT_DT:  # ④ 文字档
            app.draw_stat(); app.draw_top(); app.draw_scales(); app.last_text = now
    dt = time.time() - now
    if dt < TOUCH_DT: time.sleep(TOUCH_DT - dt)   # ⑤ 补足 8ms，避免空转烧 CPU
```

**设计要点**
- **单线程 + 时间片轮转**，没有多线程/async。触摸延迟靠「每轮先 poll 触摸」保证。
- `step()` 里的采集是**非阻塞**的：`sd_poll_frame()` 没就绪就 return，还会在核停了的时候补一次 `sd_start()`（`apps_scope_dual.py:228-236`，注释记录过一个 bug：v4 改成只轮询后漏了重新启动，核永久停住 → `st_valid` 恒 0 → UI 判定 FPGA 路径不可用 → 一直走回退）。
- 主循环末尾 `time.sleep` 把周期补到 8ms ⇒ **即使什么都没干也要醒 125 次/秒**，这是固定开销的一部分（但很小，`touch` 档实测 0.152 ms/次）。

### 6.2 缓存策略（性能的关键，共 6 层）

| 缓存 | 位置 | 作用 |
|---|---|---|
| ① 字形缓存 `_GLYPH` / `_GLYPH_W` | `:83-125`，`_install_text_cache(scr)` 把 `scr.text` 换成带缓存的版本 | 每个 (字符,大小,粗体,中文,等宽,颜色) 只渲染一次 PIL 图，之后只 `paste`。★ 注释：`fbui.text()` 画一个 CJK 字符要 **1.1~1.3 ms** |
| ② 波形底图 `bg_raw` | `:394-397` | 绘图区背景预转成原始字节，每帧 `buf[:] = self.bg_raw` 而不是重画 |
| ③ 顶栏图 `_tp_img` | `:413-423` | 顶栏背景切片缓存 |
| ④ 参数区 `_stat_bg` + `_cell_bg[ck]` | `:360, 516` | 参数两行的整块底图 + 每个数值格的底图（按「选中/未选中」两态缓存） |
| ⑤ 卡片区 `_cd_cache[i]` / 控制行 `_ct_cache[bi]` | `:681, 716` | 五张卡 / 控制按钮的渲染结果，按内容 key 缓存，只有 key 变了才重画 |
| ⑥ 刻度区 `_sc_img` | `:544` | 刻度整块切片缓存 |

**加上「零拷贝 blit」**（`:128-136` 注释）：`wave_buf` 是 `bytearray`，`self._bp` 是它的 ctypes 视图，地址稳定 ⇒ 用 `memmove` 一次贴上去。**上一版试过 `create_string_buffer(data)`，每帧反而多拷 1 MB，更慢。**

### 6.3 ★ 五个调节项

```python
/* apps_scope_dual.py:62 */
FIELDS = ["V/div", "垂直位置", "Time/div", "水平位置", "触发电平"]
```
点「当前项」按钮在 5 项之间循环（实测切换 P50=14.0 ms / P95=23.0 ms，目标 P95<60ms PASS）。另有 `fine` 微调模式。

**弹层（3 个）**
- 通道弹层 `panel == "ch"`：CH1 / CH2 复选 + 确定（**可同选，至少留一个**）
- 模式弹层 `panel == "mode"`：Auto / Normal / Single + 确定（单选）
- 高级触发 `panel == "adv"`：独立页 —— 触发源 / 边沿 / 电平 / 预触发 / Holdoff + 返回

**AUTO**（`:845`）：定 3 周期时基 + 75% 幅度量程 + 水平位置归零。**关键约束**：必须等**新鲜帧**到手再调（注释记录：刚进来时 `self.m.m[]` 还是上次运行残留的测量，用它去 AUTO 会把时基定错，实测定成 20us 而 2kHz 该是 150us）⇒ 先空跑 `AUTO_WARM = 40` 轮（≈120ms）再开始。

### 6.4 ★★ 移植第一优先级发现：`USE_FPGA_ENVELOPE = False` 硬编码

```python
/* apps_scope_dual.py:182-205 */
# ★★ 波形暂时改走 C 回退路径（2026-10-10）
# 原因：PL 的列包络写入有 bug —— 实测【恒定只有 95 列有数据】，
#   与 win_len(256/512/1024/2048/4096) 和 dec(1/2/3/6/12) 都无关，
#   固定比例 9.375%（= 96/1024）。列 95~1007 从未被写入（读回全 0）...
USE_FPGA_ENVELOPE = False
self.fpga_env = False
if USE_FPGA_ENVELOPE and self.hw.hw:
    ...
self.m.commit(self.hw)
self.push_window()          # :205

def push_window(self):      # :207-217
    """把当前显示窗口告诉 PL（包络只在这段采样点上算）"""
    if not (self.fpga_env and self.hw.hw):
        return                  # ★★ 直接 return —— PS 从来没写过 WIN_START/WIN_LEN/COL_STEP
    span = max(16, min(DEPTH, self.m.tb.span))
    start = int(self.m.hpos * span / float(GRID_C))
    ...
    self.hw.set_window(start, span)
```

**这是 95/1008 列 bug 的另一半原因**（定量证明见 `两个遗留问题分析.md` §1）：
- `USE_FPGA_ENVELOPE = False` ⇒ `fpga_env = False` ⇒ **`push_window()` 永远提前 return** ⇒ `sd_set_window()` **一次都没被调用** ⇒ PL 的 `COL_STEP` 一直是 AXI 寄存器默认值 `24'd1008`（而这个默认值是错的，正确应为 16128）。
- 修好 PL 之后，**必须同时把 `USE_FPGA_ENVELOPE` 改成 True**，否则 PL 修了也白修。

### 6.5 版本漂移提醒

`apps_scope_dual.py:196` 这一行是 2026-10-10 临时加的。若移植时用工程包这份，**必须决定是保持 False（先能用）还是改 True（依赖 PL 修好）**。建议：**第一次上板保持 False**，先保证「能看到正确波形」，PL 修好并验证后再切 True。

---

## 7. ★ `fbui.py` / `desktop.py`：能不能用他的？——**都不能，必须用我们的**

### 7.1 规模与接口对比

| | 他的（工程包） | 我们的（`handover\board_ui\`，= 板上的） | 板端 md5 |
|---|---|---|---|
| `fbui.py` | 18105 B | **52590 B** | `13ff672a762a28f4f3444fa6df2bf61f` |
| `desktop.py` | 51025 B | **76088 B** | `7d25f5b0f2f3dcbf2b6d2f4786350027` |

### 7.2 ★★ 他包里那份 `fbui.py` 连他自己的 `apps_scope_dual.py` 都跑不起来

`apps_scope_dual.py` 大量调用 `scr.to_raw(...)` 和 `scr.blit_raw(...)`：
```
:395  raw = bytearray(scr.to_raw(raw))
:506  scr.blit_raw(tbox[0], tbox[1], tbox[2]-tbox[0], tbox[3]-tbox[1], scr.to_raw(sub))
:565  raw = scr.to_raw(scr.img.crop(b))
:608  scr.blit_raw(x0, y0, w, h, buf)
:633  scr.blit_raw(x0, y0, w, h, buf)
```
**但工程包里的 `fbui.py` 里根本没有 `to_raw` / `blit_raw` 这两个方法**（实测 grep：只有 `flush()` 里有一句 `self.img.convert(self.mode).tobytes()`）。

⇒ **工程包里的 `fbui.py` 是一份残留的旧版本**；他板子上真正在跑的 `fbui.py` 更新（有 `to_raw`/`blit_raw`），但**没有被收进 56 文件包**，我们没法拿到。
（旁证：`ACCEPTANCE_EVIDENCE.md` 里讨论过 `fbui.blit_raw() 是逐行 Python 切片赋值：328 行 x 每行 3024 字节` —— 说明他板上那份确实有 `blit_raw`。）

**而我们的 `fbui.py` 恰好有这两个方法，签名完全一致**：
```python
/* 我们的 fbui.py:494,502 */
def to_raw(self, im):        return im.convert(self.mode).tobytes()
def blit_raw(self, x0, y0, w, h, data):   # 逐行切片赋值，:514-517
```
⇒ **结论：用我们的 `fbui.py`，不要用他包里的。这既是「不能」也是「正好合适」。**

### 7.3 我们的 `fbui.py` 还多出他需要的其它接口

| 他 `apps_scope_dual.py` 需要 | 我们的 fbui | 他的包 fbui |
|---|---|---|
| `from fbui import back_hit, btn, hit` | ✓ | ✓ |
| `scr.img`（PIL Image） | ✓ `:263 self.img = Image.new("RGB",...)` | ✓ |
| `scr.text(..., cn=, mono=, anchor=)` | ✓ `:548` 手写 anchor 实现（因为 **PIL 7.0.0 原生不支持 anchor**） | ✓ |
| `scr.tw(s, size, bold, cn, mono)` | ✓ `:578`，带 key 缓存 | ✓ |
| `scr.to_raw` / `scr.blit_raw` | ✓ | **✗ 缺失** |
| `Touch.poll(move=True)` | ✓ | ✓ |
| `find_touch()` | ✓ | ✓ |

**`find_touch()` 两边实测逐字符相同**：
```python
for line in open("/proc/bus/input/devices"):
    ... if any(k in name for k in ("Goodix", "TouchScreen", "touch", "Touch")):
            return "/dev/input/" + t
return "/dev/input/event1"
```
⇒ **触摸节点不用改**。我们板子实测 `event1 = Goodix Capacitive TouchScreen`，`/dev/input/event1` 存在 ✓

### 7.4 我们的 `desktop.py` 绝不能换成他的

我们的 `desktop.py`（76088 B）比他的（51025 B）多出一整套功能与 App：

**多出的方法**：`_init_home` / `total_pages` / `by_name` / `go_home` / `redraw_home` / `dock_action` / `card_action` / `show_weather` / `toast` / `_load_wallpaper_raw` / `_beat_loop` / `_beat`

**多出的 App（13 个）**：`icon_ai / icon_gear / icon_bell / icon_music / icon_browser / icon_novel / icon_clock` 等，对应 `APPS` 列表里 26 个条目（他的没有这些）

**板子实测我们 `desktop.py:434-465` 的 APPS 列表**包含：系统管家小白 / 设置 / 提示音 / 音乐 / **示波器** / 我的世界 / 死神VS火影 / 扫雷 / 计算器 / 时钟 / 画板 / 文件 / … / WiFi / 壁纸 / 关于。

**他多出、我们需要的只有一个**：`icon_scope_dual` + 一条 APPS 条目。

**⇒ 做法：不换 `desktop.py`，只往里打一个最小补丁**（新增 1 个图标函数 + 1 条 APPS 条目），备份 + md5 校验 + 可一键回滚。详见 `部署与回滚脚本.md`。

### 7.5 一个非阻塞的移植注意点：色温补偿

我们的 `fbui.Screen` 用 `ColorDraw` 包装 PIL 的 `ImageDraw`，在**绘制时**做色温补偿（`comp_color` / `_lut`）。而 `to_raw()` / `blit_raw()`（`:494-517`）**不走 LUT** —— 文档字符串说要过补偿，实现里没有。他的 `apps_scope_dual.py` 正是只用 `to_raw`/`blit_raw` 贴波形区。

⇒ **后果**：波形区的颜色不受色温补偿影响，和周围用 `ColorDraw` 画出来的 UI 可能有轻微色差。
⇒ **但这与现状一致**：我们的 `apps_scope.py` 也走同一套 `to_raw`/`blit_raw`，所以**不是新引入的问题**，不用在移植时处理。记录在此以免后面误判。

---

## 8. ★ CNN 链路端到端分析（新增，按 Lead 补充要求）

### 8.1 完整链路（实测 + 源码确认）

```
他的双通道示波器（PL @ 0x43CC0000）→ 采真波形
        │
        │   ★ 现状：这一跳【还没有接线】
        ▼
我们的 /home/zynq/waveform_ai.py（41538 B）
  一维波形 → STFT 时频图 → 缩放 28×28 → int8 图像
        │
        ▼
我们的 CNN（PL，两个独立 HLS IP）
  0x43CD0000  cnn_conv_pool_q   （卷积+ReLU+最大池化）
  0x43CE0000  cnn_fc_q          （全连接）
        │
        ▼
/home/zynq/infer_local.py（11279 B）—— 板端 /infer 实现
        │
        ▼
/home/zynq/cloud_api.py（HTTPServer, port 8768）—— 暴露 /infer
   ★ 对应板上运行中的 cloud-api.service（实测 active）
        │
        ▼
UI / agent（显示 / 语音播报）
```

**我们板子实测的 CNN IP 存在性**（只读 `/dev/mem`）：

| 地址 | 读出值 | 含义 |
|---|---|---|
| `0x43CC0034` | `0x53434F50` | 我们的 `scope_cap_axi`（"SCOP"） |
| `0x43CB0034` | `0x47505532` | 我们的 `gpu2d_axi`（"GPU2"） |
| `0x43CD0000` | `0x00000004` | ★ CNN IP 1 在（与 Lead 实测一致） |
| `0x43CE0000` | `0x00000004` | ★ CNN IP 2 在（与 Lead 实测一致） |
| `0x43C50000` | `0x01000000` | `audio_formatter` |
| `0x43C60000` | `0x00010000` | `i2s_receiver` |

DT 里**没有** CNN 节点，也**没有** scope 节点 ⇒ 这两个走 `/dev/mem` 裸访问，**地址冲突是 PL 级的，不是 DT 级的**（这一点对设备树方案很重要，见 `设备树补丁清单.md` §5）。

### 8.2 `waveform_ai.py`（41538 B）——数据源是什么？

**★ 结论：它的数据源既不是我们的 `scope_cap`，也不是他的 `scope_dual` —— 它根本不碰硬件。**

```python
/* waveform_ai.py:74-82 头部 import：argparse/array/json/math/os/random/struct/sys/time */
/* 全文没有 /dev/mem、没有 mmap、没有 0x43 系列地址、没有 import scope/scope_capture */
```

它是一份**纯算法 + 自测库**，三条数据入口：

| 入口 | 说明 |
|---|---|
| `gen_wave(kind, n=SCOPE_POINTS, fs=FS_DEFAULT, freq=..., ...)` `:146` | **合成**波形（10 类）—— `--demo` 用这个 |
| `--classify 波形.bin` `:896,917` | 从**文件**读波形 |
| **被调用方传入** `waveform_to_image(samples, ...)` `:487` | ★ 真正生产路径：`infer_local.infer_waveform(data)` 把 HTTP 请求里的 `data` 数组传进来 |

关键常量与约束：
```python
SCOPE_POINTS = 4096      # ★ 示波器采集深度
CNN_SIZE = 28            # ★ 和 PL 上 CNN 加速器的输入尺寸一致
```
```python
/* waveform_ai.py:442-443 */
if n != SCOPE_POINTS:
    raise ValueError("采集长度必须是 %d，实际 %d" % (SCOPE_POINTS, n))
```

**⇒ ★ 兼容性好消息**：`SCOPE_POINTS = 4096` **正好等于他示波器的 `DEPTH = 4096`**（`scope_dual.c:83`、`scope_dual.py` 的 `DEPTH`）。所以**他的 `read_frame_locked(ch1, ch2, 4096)` 出来的 4096 点，可以直接喂给 `waveform_to_image()`**，中间不需要重采样。

**⇒ 要改成读他的 `scope_dual`，改哪里？**
- **不用改 `waveform_ai.py` 一个字符**（它是参数化的）。
- 要改/新增的是**取数适配层**。现在这一层是：
  ```
  scope_capture.py  →  _get_scope()  →  from scope import Scope  →  libscope.so  →  我们的 scope_cap @0x43CC0000
  ```
  ```python
  /* scope_capture.py:70-76,432-438 */
  def _get_scope():
      from scope import Scope            # ★ 我们的单通道示波器
  class FakeScope(object):
      def __init__(self, *a, **k):
          self.base = 0x43CC0000          # ★ 确认我们的基址
  ```
- **两种改法**：
  1. **（推荐，零改动）** 保持 `scope_capture.py` 读我们的 `scope_cap`，**另外**新增一个 `scope_capture_dual.py`：`from scope_dual import ScopeDual` → `sd_read_frame_locked(buf1,buf2,4096,info)` → 返回 4096 点。让 `/infer` 的调用方（或 agent）选择用哪个源。**CNN 链路和两个示波器全部解耦**。
  2. **（有风险）** 把 `scope_capture._get_scope()` 改成读 `scope_dual`。这会**同时**改掉 `scope_policy.py --demo`（`scope_policy.py:377 import scope_capture as SC`）的行为，而且要把 10 位原始码的语义、`V_FULL` 换算、DDS（`set_dds` 走的是我们 scope 的 DDS）一起搬 —— **不建议**。
- ★ **如果按 A1 方案把他的示波器搬到 `0x43D00000`，那么上面两条都不用做** —— 我们的 `scope_cap`（0x43CC0000）和 CNN 链路**一行都不动**。这是 A1 相对 A2 的**额外决定性理由**（原来的理由只是「改动最小」）。

### 8.3 `cnn_linux.py`（33429 B）——mmap 了哪些地址、IO 格式

**mmap 的地址（实测源码确认）**

| 类 | 基址 | 说明 |
|---|---|---|
| `HlsIp(CPQ_BASE)` | **`0x43CD0000`** | `cnn_conv_pool_q`（卷积+ReLU+池化） |
| `HlsIp(FCQ_BASE)` | **`0x43CE0000`** | `cnn_fc_q`（全连接） |
| `DmaBuf` 内存池 | **`POOL_BASE = 0x3E000000`** | ★ 预留物理 RAM，用 **`/dev/mem` 再映射一份（不可缓存）**，数据只走这一份（`cnn_linux.py:220,240,255`） |

```python
/* cnn_linux.py:77-78 */
CPQ_BASE = 0x43CD0000
FCQ_BASE = 0x43CE0000
/* :220 */
POOL_BASE = 0x3E000000
/* :255 唯一一份映射：/dev/mem，不可缓存 */
self.mm = mmap.mmap(self._pool_fd, self.alloc, mmap.MAP_SHARED,
                    mmap.PROT_READ|mmap.PROT_WRITE, offset=paddr)
```

> ★ **`POOL_BASE = 0x3E000000` 是一个隐藏的移植约束**：它要求 DDR 顶部（≥0x3E000000）被留出来给 CNN 用。我们板上 `system.dtb.bak_mem992` 这个备份名就暗示之前调过 memory 大小。**合并新 PL 时不能动 DT 的 `memory` 节点**，否则 CNN 会写到 Linux 正在用的内存上。（见 `设备树补丁清单.md` §5 的红线。）

**输入 / 输出数据格式**

```python
/* cnn_linux.py:401-402 —— DMA 缓冲，都按 128 字节对齐 */
self.img = DmaBuf(832,  "img")   # 28*28=784，padding 到 832
self.w1  = DmaBuf(128,  "W1")    # 72
```
- **输入图**：`28×28 = 784` 字节，**uint8**，缓冲 832 字节（784 padding 到 128 对齐）。
- **量化**：`int8 = u8 - 128`（`cnn_linux.py:426-427`：`img_i8 = bytes(((b - 128) & 0xFF) for b in img_u8)`）—— 注释强调和裸机一致。
- **权重布局**（AI 交付包 4480 B，128 字节对齐）：`img[784] u8 | W1[72] i8 | W2[1152] i8 | WF[4000] i8 | label u32`（`:416-418`），解析出 `list(struct.unpack("<72b", ...))` / `"<1152b"` / `"<4000b"`。
- **网络结构**：`28×28 ─conv1(1→8, 3×3)+ReLU+pool2─→ 13×13×8 → conv2 → fc`（`:53`）。
- **★ 每层独立 MFQ（不是全局）**：
  ```python
  MFQ = 119          # 旧 MNIST 校准值（向下兼容，别删）
  MFQ_C1 = 201       # 波形模型 conv1
  MFQ_C2 = 371       # 波形模型 conv2
  MFQ_FC = 1390      # 波形模型 fc
  ```
  注释说明：`MFQ` 在 HLS 里是 **s_axilite 寄存器**，每次调用独立生效；溢出约束 `max|acc| × MFQ < 2^31` 逐层实测余量 196×/172×/115×。**绝对不要退回用一个全局 MFQ**。
- **requantize**：`out = sat/relu((acc * MFQ) >> 16)`，int8 权重/激活，**int32 累加**，最后量化回 int8 —— 与他 `CNN_RESOURCE_BUDGET.md` 第五节的约定一致 ✓
- **★ 每层跑两遍**：`run_cpq_twice()`（`:581-591`）—— 因为第一次跑不确定（缓存/DMA 未预热），用第二遍。代价「每层多 4~7ms，本工程一组 11ms → 22ms，完全可接受，换来确定性」。

### 8.4 `infer_local.py`（11279 B）——板端 `/infer` 实现

**不是 HTTP 服务器本身，是 `/infer` 的处理函数**（被 `cloud_api.py` 调用）。

```python
/* infer_local.py:8-9 协议 */
POST /infer
{ "type": "waveform"|"chat", "data": [...], "hint": "...", "api_key": "..." }
```
```python
/* infer_local.py:65-72  懒加载，进程内只建一次 */
def _ensure():
    import cnn_linux as CL
    import waveform_ai as WA
    c = CL.Cnn(verbose=False)
```
```python
/* infer_local.py:113-144  infer_waveform 返回体 */
{
  "ok": True, ...
  "engine": "PL 加速器（cnn_conv_pool + cnn_fc）",
  "accel_regs": {"conv_pool": "0x43CD0000", "fc": "0x43CE0000"},   # ★ :139 显式声明
  ...
}
```
- `infer(body, cloud_chat_fn=None)` `:146` 是统一入口，按 `type` 分派：`waveform` → `infer_waveform(data, hint)`；`chat` → 云端。
- `_to_image(data, hint)` `:90`：`data` 是 **784** 长度时按「已经是图」处理，否则按波形走 `waveform_ai.waveform_to_image()`。
- `health()` `:198` 健康检查。
- **注册点**：`cloud_api.py:865-885`
  ```python
  import infer_local
  return infer_local.infer(body, cloud_chat_fn=_chat)
  ...  return infer_local.health()
  ```
  `cloud_api.py` 是 `http.server.ThreadingHTTPServer`（`:54`），默认 **port 8768**（`:65`），对应实测在跑的 `cloud-api.service`。

### 8.5 ★ 端到端数据流（从他的示波器到分类结果）

```
① 他的 PL scope_dual_core 采集：2 通道 × 4096 点 × 10 位，20 MSPS，双 bank ping-pong
   │  帧周期实测 0.47~0.48 ms（他 evidence）
   ▼
② PS：sd_read_frame_locked(buf1, buf2, 4096, info)
   /dev/mem O_SYNC 强序读，锁 bank → 读 → ACK
   │  数据形态：ctypes.c_ushort[4096] × 2，值域 0..1023（10 位原始码）
   ▼
③ 取 1 个通道的 4096 点 → waveform_ai.waveform_to_image(samples)
   │  内部：quantize_8bit → 加窗(STFT_WINDOW) → radix-2 FFT → STFT(win, hop)
   │        → spectrum_to_image：对数压缩 + resize_bilinear 到 28×28 + 量化 0..127
   │  输出：784 字节 uint8（CNN 输入）
   ▼
④ cnn_linux.wave_classify(img_u8_784) → Cnn
   │  写入 DmaBuf(img, 832B, 0x3E000000 不可缓存) ；img_i8 = u8 - 128
   │  run_cpq_twice(28,28,1,CB1, img, w1, fb1, MFQ_C1=201)   每层跑两遍
   │  run_cpq_twice(..., MFQ_C2=371)
   │  run_fc(..., MFQ_FC=1390)
   │  每次 start_and_wait() 是寄存器轮询（poll 间隔 2ms 起，timeout 5s）
   ▼
⑤ 输出：10 类分类 idx + 名称 + logits
   ▼
⑥ infer_local.infer_waveform 组装 JSON → cloud_api 的 /infer 返回
   ▼
⑦ UI / agent 显示 + 语音播报
```

**延迟量级（据他 evidence + 源码常量）**

| 段 | 量级 | 来源 |
|---|---|---|
| ① 采一帧 | **0.47~0.48 ms** | 他 evidence（FPGA 帧周期） |
| ② 搬 4096 点经 /dev/mem O_SYNC | 与 2016 次包络读同量级（他实测 step 一整步 **0.56 ms**，含读帧+2×sd_measure+2×sd_saturation） | `ui_breakdown_final.txt:9` |
| ③ STFT + 缩放（纯 Python，含 radix-2 FFT、双线性缩放） | **未在他 evidence 里单独测过** ⇒ 需我们自测 | — |
| ④ CNN 推理 | 他 README 口径 **「一组 11ms → 22ms」**（因为每层跑两遍） | `cnn_linux.py:590-591` |
| ⑤⑥ JSON 组装 + HTTP | <1 ms | — |

⇒ **端到端主要成本在 ④ CNN（约 22 ms）和 ③ STFT（待测）**，采集与搬运都不是瓶颈。

**★ 现状的关键结论：第 ③ 步之前的那一跳（示波器 → waveform_ai）现在根本没有自动接线。**
`infer_local.infer_waveform(data)` 的 `data` 是**从 HTTP 请求体里来的数组** —— 也就是说，**现在必须由调用方（PC / agent / 另一个脚本）先把 4096 个点作为 JSON 数组发过来**。板子上没有任何模块会自动从示波器取一帧喂给 CNN。

⇒ **这就是「把他的示波器接进来」真正的增值点**：加一个「示波器 → waveform_ai」的适配器（`scope_capture_dual.py` + agent 里的一个动作），就能做成「按一下 → 采真波形 → CNN 分类 → 语音播报」。这是本次移植**唯一真正新增的软件工作量**（约 60~100 行），其余都是照搬 + 改地址。

### 8.6 与他 `CNN_RESOURCE_BUDGET.md` 第五节约定的差距

他写的约定（`evidence/CNN_RESOURCE_BUDGET.md:50-56`，标为「规则3」）：

| # | 他的约定 | 我们 CNN 现状 | 差距判定 |
|---|---|---|---|
| 1 | **另起独立 IP，不要塞进 `scope_dual_*`** | ✓ `cnn_conv_pool_q` @0x43CD0000、`cnn_fc_q` @0x43CE0000 是**两个独立 HLS IP**，和 scope 无关 | ✅ **完全满足** |
| 2 | **单独 CNN 时钟 100~150 MHz**，不与采样/像素时钟混 | ⚠️ 用户态看不到时钟树，**必须由 vivado-builder 在 BD 里确认**（看 `cnn_*` 的 `ap_clk` 是否独立、频率多少） | ⚠️ **待 Vivado 核实**，列入交接检查单 |
| 3 | **大数据走 AXI HP / DMA**；控制走 AXI-Lite | 控制：✓ AXI-Lite（`HlsIp` 寄存器读写）。数据：✓ 走 `DmaBuf` @0x3E000000（预留 RAM，不可缓存），HLS IP 用 `m_axi` 从那里搬 ⇒ **实质是 AXI 主口**，但**是不是 `S_AXI_HP` 需在 BD 里确认**（若是 `S_AXI_GP` 会严重限速） | ⚠️ **待 Vivado 核实**；用户态看不到 |
| 4 | **权重/激活 int8，累加 int32，最后量化回 int8** | ✓ 完全一致：`MFQ_C1=201/MFQ_C2=371/MFQ_FC=1390`，`out = sat/relu((acc*MFQ)>>16)`，`max\|acc\|×MFQ < 2^31` 逐层实测余量 196×/172×/115× | ✅ **完全满足且更细**（他只有一个全局概念，我们是逐层） |
| 5 | **接入后必须重跑 `report_utilization`**，确认预留仍成立 | ❌ 未做（本次合并新增 scope_dual_core/axi，资源会涨） | ❌ **vivado-builder 必做**，列为验收硬条件 |

**⇒ 总结判断：我们的 CNN 现状与他的约定差得很少**，实质差距只在两点，而且**都在 Vivado 侧、不在 PS 侧**：
1. **时钟独立性**（约定 2）—— 需 Vivado 确认；
2. **数据通路是否 HP**（约定 3）—— 需 Vivado 确认；
（约定 5 是流程要求，不是设计差距。）

**★ 反向结论（很重要，避免做无用功）**：他 `CNN_RESOURCE_BUDGET.md` 第二节给 CNN 预留了 `64 DSP / 24 BRAM / 15000 LUT`，但**他的设计里根本没有 CNN**（他只有 scope_dual_core/axi，实测 DSP=2 / BRAM=10）。**我们才有 CNN。** 所以这份文档的「CNN 预留」是**他写给未来的、空的额度**；而我们的 CNN 是**已经在跑的实体**。
⇒ **合并时不要把「他的 CNN 预留」当成「他的资源占用」去加总**，否则会严重高估占用、误判资源不够。

---

## 9. ★ 移植到我们板子要改哪几处（汇总）

| # | 改什么 | 文件 : 位置 | 改成什么 | 风险 |
|---|---|---|---|---|
| **1** | ★★ 标记文件解耦 | `scope_dual.py:28` | `MARKER = "/home/zynq/.scope_dual_addr"` | **不改就两个示波器抢地址** |
| **2** | 基地址 | `scope_dual.py:29` | `DEFAULT_BASE = 0x43D00000`（待 vivado-builder 定） | 中；一行 |
| **3** | 新增标记文件 | `/home/zynq/.scope_dual_addr` | 内容 `0x43D00000` | 低；纯新增 |
| **4** | 桌面入口 | `desktop.py` | 新增 `icon_scope_dual()` + APPS 里加一条 | 中；要备份 |
| **5** | 版本魔数一致性 | `scope_dual.c` 不改 / **RTL 由 vivado-builder 定** | **保持 SCP3（0x53435033）**，或 C 里加 SCP4 到白名单 | **高**：魔数不匹配会静默无硬件 |
| **6** | `USE_FPGA_ENVELOPE` | `apps_scope_dual.py:196` | 第一次上板**保持 False**；PL 修好后再改 True | 低（但决定性能） |
| **7** | 前级换算常量 | `scope_processing.py` 的 `V_FULL` | 我们也是 3PA1030 同款前级 ⇒ **大概率不用改**；实测确认 | 低 |
| **8** | 分辨率 | `apps_scope_dual.py:36-43` | 我们也是 1024×600 ⇒ **不用改** | — |
| **9** | 触摸节点 | `fbui.find_touch()` | 两边逐字符相同 ⇒ **不用改**（实测 event1 = Goodix） | — |
| **10** | `fbui.py` / `desktop.py` | — | ★ **用我们的，不用他的**（见 §7） | 高（换错就全崩） |
| **11** | `libscopedual.so` | — | ★ **板上 gcc 重新编译**，不要传他编好的 | 中 |
| **12** | 桌面入口挂载 | — | 不动我们 26 个既有 App 的任何一个 | 红线 |

**硬红线（用户要求：现有功能一个都不能删）**
```
不允许动：/home/zynq/ui/fbui.py
          /home/zynq/ui/apps_scope.py     （我们的单通道示波器）
          /home/zynq/ui/scope.py
          /home/zynq/ui/libscope.so
          /home/zynq/.scope_addr          （★ 我们的示波器基址标记）
          desktop.py 里既有 26 条 APPS 条目
          /mnt/boot/*                     （本次任务只分析，不写）
```

---

## 10. 交付与下一步

- 设备树：见 `设备树补丁清单.md`（★ 基于**我们板子实测的 9 个节点状态**，不是照抄他的文档）
- 部署/回滚：见 `部署与回滚脚本.md` + `deploy_ps.py` + `rollback.py`
- 两个遗留问题：见 `两个遗留问题分析.md`（95/1008 列的**定量根因** + CPU 的真实账）

### 需要 Lead / 用户决策的问题

| # | 问题 | 建议 |
|---|---|---|
| D1 | 他的示波器基地址最终定在哪？ | **A1：0x43D00000**（0x43C00000~0x43CE0000 已占满；0x43CF0000 可留备用）。理由比原来更硬：**我们的 CNN 链路依赖 `scope_cap` 留在 0x43CC0000，一搬就要改 CNN 链路** |
| D2 | RTL 版本魔数定 SCP3 还是 SCP4？ | **SCP3**（包里 RTL 现状，C 已支持，零改动）。若要 SCP4 则必须同步改 `scope_dual.c:284` 白名单 |
| D3 | 原示波器和新示波器的桌面形式？ | **两个图标并存**（「示波器」= 我们的，`apps_scope`；「示波器x2」= 他的，`apps_scope_dual`）。**不要合并** |
| D4 | `USE_FPGA_ENVELOPE` 第一次上板取什么？ | **保持 False**（先用 C 回退保证波形正确），PL 修好并验证 1008/1008 后再切 True |
| D5 | 是否要新增「示波器 → CNN → 语音播报」的动作？ | 建议做，**这是本次移植唯一真正的新增软件价值**（`scope_capture_dual.py` + agent 一个动作，约 60~100 行） |
| D6 | 我们 CNN 的 `ap_clk` 是否独立 100~150 MHz、`m_axi` 是否挂 `S_AXI_HP`？ | **需 vivado-builder 在 BD 里核实**（我们用户态看不到），见 §8.6 |
