#!/bin/bash
# ============================================================================
# 01_PetaLinux_流程.sh —— PetaLinux 2018.3 建/配/编 命令（P3 阶段参考）
#   在 Ubuntu 16.04 主机（已装 PetaLinux 2018.3 并 source settings.sh）执行。
#   硬件来自 Vivado 导出的 .hdf（P2 阶段产物）。
#   注意：本脚本是"骨架命令集"，具体 rootfs/GUI 选项按正点原子教程微调。
# ============================================================================

# ---- 0. 每次新终端：先 source 环境 ----
# source /opt/pkg/petalinux/2018.3/settings.sh      # 路径按实际安装改
echo "PetaLinux: $(which petalinux-create)"; petalinux-util --version

export PROJ=zynq_lcd_osc                       # 工程名
export HDF=~/hw/design_1_wrapper.hdf           # Vivado 导出的硬件描述

# ---- 1. 建工程（Zynq 模板）----
petalinux-create --type project --template zynq --name $PROJ
cd $PROJ

# ---- 2. 用硬件描述配置（导入 .hdf，得到设备树/驱动骨架）----
petalinux-config --get-hw-description=$(dirname $HDF)
#   进入菜单：重点
#   - Subsystem AUTO Hardware Settings → 串口/以太网/SD 确认（与板子一致）
#   - Image Packaging Configuration → Root filesystem type:
#         * 先跑通：INITRAMFS（最简单，全在 image.ub 里）
#         * 要装软件/持久化：EXT4 (SD)  —— 与正点原子教程一致
#   - Yocto Settings → 需要 Qt 时打开 meta-qt5

# ---- 3. （可选）配置内核：加 framebuffer / DRM / 触摸 ----
petalinux-config -c kernel
#   确认：CONFIG_FB / DRM_XLNX / CONFIG_FB_XILINX(旧) 之类显示相关已使能

# ---- 4. （可选）根文件系统：加 Qt/LVGL/工具 ----
petalinux-config -c rootfs
#   Filesystem Packages → 勾选 qtbase / qt5 / 或自定义 app

# ---- 5. 编 rootfs 里的自研应用（把示波器 app 放进来）----
#   把 app 源码放到 ./project-spec/meta-user/recipes-apps/<app>/
#   petalinux-create -t apps --template c --name scopeapp --enable
#   然后 petalinux-build

# ---- 6. 构建 ----
petalinux-build

# ---- 7. 打包启动镜像（BOOT.BIN：FSBL + bitstream + u-boot）----
petalinux-package --boot --fsbl images/linux/zynq_fsbl.elf \
                  --fpga images/linux/system.bit \
                  --u-boot --force
#   产物：images/linux/BOOT.BIN  +  images/linux/image.ub

# ---- 8. 拷到 SD 卡（FAT32 分区）----
#   cp images/linux/BOOT.BIN images/linux/image.ub  /media/<SD>/
#   若 rootfs 用 EXT4：另建 ext4 分区放 rootfs.ext4 解开的文件

echo "== 完成：BOOT.BIN + image.ub 在 images/linux/ =="

# ---- 9. 上板后自检 ----
#   dmesg | grep -i -E 'drm|fb|vdma|lcd'      # 看显示驱动是否加载
#   ls -l /dev/fb0                            # framebuffer 是否存在
#   cat /dev/urandom > /dev/fb0               # 花屏=能画
#   ls /dev/video* /dev/vdma*                 # 采集节点
