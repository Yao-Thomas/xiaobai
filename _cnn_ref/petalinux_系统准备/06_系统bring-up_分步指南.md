# 06 · 系统 bring-up 分步指南（先做系统）

> 目标：让 **正点原子 领航者 ZYNQ7020 跑起 Linux 系统 + 7 寸 RGB 屏出画面**。
> 这一步是"地基"；示波器/GUI/AI 都只是之后往系统里加软件。
> 顺序：**P0 环境（主机） → P1 先用现成镜像证明能启动 → P2 显示硬件 → P3 PetaLinux 构建 → P4 屏幕出画面**

参考：[PetaLinux 2018.3 安装全攻略](https://blog.csdn.net/weixin_29192365/article/details/159022467)、
[ubuntu16.04 装 vivado2018.3+petalinux2018.3](https://blog.csdn.net/gu511/article/details/130664324)、
[ZYNQ-Linux 启动文件构建全解析](http://openedv.com/forum.php/archiver/forum.php?mod=viewthread&tid=351760)、
[SD卡启动 Linux 步骤](https://huaweicloud.csdn.net/6549fc088c4ad05cd82aabbd.html)

---

## P0 · 主机环境（你在 Windows 上操作）

### 0.1 装 Linux 虚拟机（PetaLinux 只能在 Linux 跑）
1. 装 **VMware Workstation Player**（免费）或 VirtualBox。
2. 下载 **Ubuntu 16.04.7 Desktop (amd64) ISO**。
3. 新建虚拟机：**磁盘 ≥100GB（建议 150GB）、内存 ≥8GB、CPU ≥4 核、网络 NAT**。
4. 装好 Ubuntu，能进桌面。

> ⚠️ 别用 Ubuntu 18.04/20.04——PetaLinux 2018.3 官方配套是 **16.04**。

### 0.2 装依赖库（在 Ubuntu 终端里）
```bash
sudo apt-get update
sudo apt-get install -y tofrodos iproute2 gawk gcc g++ git make net-tools \
  libncurses5-dev tftpd zlib1g-dev libssl-dev flex bison libselinux1 gnupg wget \
  diffstat chrpath socat xterm autoconf libtool tar unzip texinfo zlib1g-dev \
  gcc-multilib build-essential libsdl1.2-dev libglib2.0-dev screen pax gzip \
  python3 python3-pip
# PetaLinux 要求 /bin/sh 指向 bash（Ubuntu 默认是 dash）：
sudo dpkg-reconfigure dash      # 弹出选 No
```

### 0.3 装 Vivado 2018.3（Linux 版）
- 下载 **Vivado 2018.3 (Linux Self Extracting Web Installer)**，装 **Vivado HL WebPACK**（免费，含 Zynq-7020）。
- 安装目录建议 `/tools/Xilinx`（纯 ASCII、别带空格）。

### 0.4 装 PetaLinux 2018.3
1. Xilinx 官网下载 **`petalinux-v2018.3-final-installer.run`**（约 7GB+）。
2. 安装（**不要 sudo**，用普通用户）：
```bash
chmod +x petalinux-v2018.3-final-installer.run
mkdir -p ~/petalinux/2018.3
./petalinux-v2018.3-final-installer.run ~/petalinux/2018.3
```
3. 每次新终端先 source 环境（建议写进 `~/.bashrc`）：
```bash
source ~/petalinux/2018.3/settings.sh
```

### 0.5 验证
```bash
petalinux-util --version      # 应打印 2018.3
vivado -version               # 应打印 2018.3
```

---

## P1 · 先用正点原子现成镜像，证明板子能启动（**关键：不改任何东西**）

> 目的：把"系统能跑 + 屏能亮"先证实。通了再谈自建工程。

### 1.1 拿镜像
- 到正点原子资料下载 **《领航者 ZYNQ 之 Linux 开发指南》配套资料**（含现成 Linux 镜像：`BOOT.BIN`、`image.ub`，或一整张 SD 卡镜像 `.img`）。

### 1.2 烧 SD 卡
- 准备 **≥8GB Class10 microSD**。
- **若是整卡 `.img`**：用 Win32DiskImager / balenaEtcher 直接写。
- **若是分开的文件**（BOOT.BIN + image.ub）：
  - SD 第一个分区 **FAT32**（≥1GB），放 `BOOT.BIN` + `image.ub`；
  - 若 rootfs 是 EXT4，再建第二个 ext4 分区放根文件系统（按教程）。

### 1.3 板子接线与启动
1. 拨码：**SD 启动**（正点原子板有 SD/QSPI/JTAG 选择）。
2. 接 **USB 串口**（CH340 → 电脑），**115200-8N1，无流控**。
3. 接 **7 寸 RGB LCD**（排线别插反），接背光/电源。
4. 上电。

### 1.4 期望现象 / 排查
- 串口应打印 `U-Boot` → `Starting kernel` → Linux 启动日志 → 登录提示或 shell。
- LCD 应点亮（显示 logo/控制台/桌面，取决镜像）。

排查清单：
| 现象 | 查 |
|---|---|
| 串口全无输出 | 串口号/波特率/驱动；拨码是否 SD；SD 是否插好 |
| U-Boot 后卡住 | `image.ub` 缺失/损坏；分区格式 |
| 进内核但 panic | rootfs 分区/`bootargs` 与教程不一致 |
| 串口有、屏黑 | LCD 排线/背光；镜像是否带显示；时序 |
| 参考 | [SD卡启动 Linux](https://huaweicloud.csdn.net/6549fc088c4ad05cd82aabbd.html)、[启动失败贴](http://www.openedv.com/forum.php/thread-347716-1-1.html) |

**✅ P1 通过标准**：串口进到 Linux 命令行/登录，且 LCD 有显示。

---

## P2 · 显示通路（Vivado）—— 简要
- 打开正点原子 **LCD 显示 Vivado 工程**为基线；或按 `run_bd_display.tcl` 起点自建。
- PS 配置用官方板级配置；显示流水线 = VDMA + v_tc(1024×600) + v_axi4s_vid_out + GPIO。
- LCD 引脚约束按你屏排线写（`xdc/lcd_adc_template.xdc` 模板）。
- 综合实现 → 导出 `.hdf`（`write_sysdef` 方法）。
- 详见 `02_显示通路_Vivado_说明.md`。

## P3 · PetaLinux 构建 —— 简要
- 按 `01_PetaLinux_流程.sh`：`petalinux-create` → `petalinux-config --get-hw-description` → `petalinux-build` → `petalinux-package --boot`。
- rootfs 先选 **INITRAMFS**（最简单，全在 image.ub 里）；要持久化/装软件再改 EXT4。
- 详见 `01_PetaLinux_流程.sh`。

## P4 · 屏幕出画面 —— 简要
- 上板 `ls -l /dev/fb0`、`cat /dev/urandom > /dev/fb0`（花屏=能画）。
- 至此"系统 + 屏"地基完成，后面想加什么软件都行。
- 详见 `03_LCD设备树_1024x600.md`。

---

## 时间与顺序建议
1. **先启动 P0 的下载**（Vivado 2018.3 Linux + PetaLinux 2018.3，几十 GB，最耗时）。
2. 下载期间可以去做 P1 的准备（找正点原子镜像、备 SD 卡）。
3. 环境好了立刻做 P1 —— **只要 P1 通了，"能做"就已证明**。

> 卡住就把**串口完整日志**发我，我帮你看。
