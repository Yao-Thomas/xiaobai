#!/bin/bash
# ============================================================================
# build_all.sh —— P2+P3 一键流程（在 Ubuntu 16.04 主机执行）
#   前提：已装 Vivado 2018.3 + PetaLinux 2018.3，且已 source 两者环境。
#   说明：本脚本把"Vivado 建显示BD → 综合 → 导出 hdf → PetaLinux 建镜像"串起来。
#         显示 BD 的 LCD 引脚/时序需先按 run_bd_display.tcl + xdc 模板补全。
# ============================================================================
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)          # petalinux_示波器_准备/
BOARD="$ROOT/../../FPGA2026_PRJ/zynq_ai_accel/board"   # 板级产物目录(按需改)
PROJ=zynq_lcd_osc

echo "== [1/4] Vivado: 建显示 BD =="
vivado -mode batch -source "$ROOT/run_bd_display.tcl"

echo "== [2/4] Vivado: 综合/实现/bit + 导出 hdf =="
# 需先有 run_synth_display.tcl（结构同我们裸机的 run_synth_m4b5.tcl）
# vivado -mode batch -source "$ROOT/run_synth_display.tcl"
# vivado -mode batch -source "$ROOT/generate_hdf_display.tcl"
echo "   (请参照 build/run_synth_m4b5.tcl + generate_hdf_m4b5.tcl 补这两个脚本)"

HDF="$BOARD/chain_lcd.hdf"

echo "== [3/4] PetaLinux: 建工程并导入硬件 =="
source /opt/pkg/petalinux/2018.3/settings.sh 2>/dev/null || echo "  ⚠️ 先 source petalinux settings.sh"
petalinux-create --type project --template zynq --name $PROJ --force
cd $PROJ
petalinux-config --get-hw-description=$(dirname "$HDF") --silentconfig || \
  petalinux-config --get-hw-description=$(dirname "$HDF")

echo "== [4/4] PetaLinux: 构建 + 打包 =="
petalinux-build
petalinux-package --boot --fsbl images/linux/zynq_fsbl.elf \
                  --fpga images/linux/system.bit --u-boot --force

echo "== 完成: $PROJ/images/linux/{BOOT.BIN,image.ub} =="
echo "   拷到 SD 卡(FAT32) → SD 启动 → 串口 115200-8N1"
