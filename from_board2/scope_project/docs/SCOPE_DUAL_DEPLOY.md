# 双通道示波器（Dual 3PA1030）上板流程与踩坑记录

> 2026-10-09 完成
> 板子：正点原子 领航者 ZYNQ7020（16G 卡，Ubuntu 20.04.5 / 5.4.0-xilinx-v2020.2）

---

## 一、最终成果

| | |
|---|---|
| **PL** | `dsh:user:scope_dual_axi:1.0`（"SCP2"）@ `0x43CC0000` / 64K |
| | 2 通道 × 10 位 × 4096 点，双 bank ping-pong，20 MSPS |
| | 抽取 / 触发电平 / 边沿 / 触发通道 / 预触发 / Auto-Normal-Single |
| **PS** | `libscopedual.so`（板载 gcc 编译）+ `scope_dual.py` + `apps_scope_dual.py` |
| **界面** | 桌面新增「示波器x2」图标（原「示波器」保留） |
| **验证** | `VERSION=0x53435032` ✓ `CAPS=0x020A1000` ✓ `RATE=20MHz` ✓ |
| | 采集实测：CH1=893 / CH2=495（未接信号时的稳定直流） |

---

## 二、⚠️ 最重要的一条：**改 PL 必须同步改设备树**

### 这次的翻车过程

```
1. 新比特流构建成功（TIMING_MET=1）
2. 只把 .bit 写进 p1 的 system.bit        ← ★ 错在这里
3. 重启 → 内核 panic 在 clk_wzrd_probe
   Unhandled fault: imprecise external abort (0x406)
4. 黑屏，进不了系统
```

### 原因

新 PL **删掉了 camera / HDMI / i2c2**（为了腾出 ADC 的引脚），
但 p1 上的 `system.dtb` 还是老的，里面还有这 9 个节点：

```
/amba_pl/clk_wiz@43c80000        HDMI 动态时钟   ← panic 就出在这
/amba_pl/v_tc@43c90000           HDMI 时序控制器
/amba_pl/v_frmbuf_wr@43c40000    摄像头写入
/amba_pl/v_frmbuf_rd@43ca0000    HDMI framebuffer 读
/amba_pl/i2c@41600000            i2c2
/amba_pl/i2c@41600000/ov5640@3c  摄像头传感器
/amba_pl/drm_pl_disp_hdmi        HDMI 显示封装
/amba_pl/atk_hdmi_drm            HDMI DRM
/amba_pl/vcap_dvp                摄像头采集
```

内核按设备树去 probe 这些**已经不存在的寄存器** → 总线 abort → panic ✓

### 解法

用 `fdtput` 把这 9 个节点标成 `status = "disabled"`（见 `ps/patch_dtb.sh`）：

```sh
fdtput -t s system.dtb /amba_pl/clk_wiz@43c80000 status disabled
...
```

**验证方法**：先只装补丁设备树、**保持老 PL** 重启一次 ✓
老 PL 里这些外设都存在，禁用它们无害 → 如果能正常启动，说明补丁安全 ✓

---

## 三、正确的开发顺序（务必遵守）

```
1. 改 .v / BD  →  Vivado 综合实现  →  .bit + .hwh
2. ★ 同步更新设备树
      · 用 .hwh 重新生成（正规做法），或
      · 按差异给 dtb 打补丁（fdtput status=disabled）
3. ★ 先用 JTAG 烧 .bit 验证 PL 逻辑
      · 不碰 SD 卡、不重启系统、几秒见效、随时换
      · 有 JTAG 的话根本不会把板子搞黑屏
4. 确认 PL 没问题，才把【新 .bit + 新 dtb】一起写进 SD 卡
5. 写卡前先备份（这次就是靠 p1 上的备份救回来的）
```

### 关于 `.v` / `.bit` / SD 卡

| 文件 | 放 SD 卡 | FPGA 会读吗 |
|---|---|---|
| `.v` 源码 | 能放但**毫无作用** | ❌ 不读。只活在电脑的 Vivado 里 |
| `.bit` 比特流 | ✅ 必须 | ✅ u-boot 开机 `fpga loadb` 加载 |
| `system.dtb` | ✅ 必须 | ✅ 内核靠它认 PL 外设 |
| `.py` / `.so` | ✅ | PS 侧程序，放根文件系统 |

**"网传"只是传输方式**，传什么文件都行；但 **`.v` 永远不会出现在 SD 卡上**，
改 `.v` 必须在电脑上跑 Vivado 重新综合出 `.bit`。

---

## 四、引脚方案（避开 LCD）

官方 `ATK_DUAL_HS_AD` 的 26 个引脚**和 7 寸 RGB LCD 的 24 个 RGB 脚 + CLK/DE/HS 完全重合** ✗
所以这套设计**没有用官方引脚**，改到了别的空脚上：

```
AD 通道1 D1_0..D1_9 : F17 F16 G20 G19 H18 J18 L20 L19 J19 K19
AD 通道2 D2_0..D2_9 : H20 J20 L16 M18 M17 E19 E18 G18 G17 H15
adc1_clk = J14      adc2_clk = K14   (20MHz, DRIVE 8 SLEW FAST)
```

**代价**：让出 `can0` / `i2c0` / `i2c2` / `uart1` / `pl_led` / `tmds`(HDMI) / `cmos`(摄像头) / 音频 I2S 的**外部引脚**
**保住**：**LCD ✓ 以太网 ✓ 触摸 I2C1 ✓**（音频子系统内部通路保留，只把 `adcdat` 拉低）

**所以必须用杜邦线把模块的 JP1 接到上面对应的板子引脚上，不能直接插 J3。**

---

## 五、时钟方案

```
100MHz FCLK ──► clk_wiz(scope_adc_clk)
                  ├─ clk_out1  20MHz   0°  ──► 前送给 ADC 的 CLK
                  └─ clk_out2  20MHz 270°  ──► FPGA 内部采样时钟
```

**20MHz 周期 50ns，270° = 37.5ns** → 在 ADC 时钟边沿后 37.5ns 采样 ✓
3PA1030 数据约 25ns 后稳定 → 采样点落在数据窗口正中，两侧各留 ~12.5ns ✓

---

## 六、部署脚本

| 脚本 | 作用 |
|---|---|
| `install_dual_scope.py dtb-only` | 只装补丁设备树（安全验证用） |
| `install_dual_scope.py` | 设备树 + 比特流，然后重启 |
| `install_dual_scope.py rollback` | 用 p1 上的备份回滚 |
| `deploy_ps.py` | 推 C 源码 → **板上 gcc 编译** → 推 Python/UI/桌面 |
| `shot_dual.py` | 停桌面 → 跑双通道应用 → 截图 → 恢复 |
| `ps/patch_dtb.sh` | 给 dtb 打 9 节点 disabled 补丁 |
| `uboot_recover2.py` | **起不来时**：抢 u-boot，用备份老比特流 RAM 启动 |
| `revert_all.py` | 完全恢复原状（还原 bit/dtb/desktop，删掉新文件） |

### p1 上的备份

```
system.bit.bak_before_dual       4045769   装新比特流之前的老版本
system.dtb.bak_before_patch        29180   打补丁之前的老设备树
system.bit.bak_20261009_192443   4045769   更早的备份
（另有 9 个历史备份，都在）
```

---

## 七、救砖流程（板子黑屏/panic 时）

```python
python uboot_recover2.py     # 然后给板子断电重上电
```

u-boot 的 autoboot 只有 3 秒，脚本**每 150ms 敲一次回车**必定打断 ✓
然后：

```
fatload mmc 0:1 0x00800000 <备份的比特流>
fpga loadb 0 0x00800000 <字节数>
fatload mmc 0:1 0x00200000 zImage
fatload mmc 0:1 0x00100000 system.dtb
bootz 0x00200000 - 0x00100000
```

**这是纯 RAM 操作，不改卡** ✓ —— 起来之后再从网络改 p1 ✓

> ⚠️ **黑屏看门狗**（`zynq-screen-guard`）看到屏幕黑会自动重启，
> 救回来后先 `systemctl stop zynq-screen-guard` 再慢慢弄。

---

## 八、网络链路

```
板子 eth1  169.254.70.5/16  静态（/etc/network/interfaces）
电脑 以太网 169.254.70.4/16  Windows APIPA 自动
ssh board  （~/.ssh/config 里的别名）
```

**链路会抖**（ARP 条目变 Stale、前几次连接超时）→ **所有脚本都要带重试** ✓

另见 `zynq01/fpga2018/NET_WORKFLOW.md`
