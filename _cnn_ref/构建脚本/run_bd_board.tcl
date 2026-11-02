# ============================================================================
# run_bd_board.tcl —— 板级就绪的 Block Design（领航者 ZYNQ 7020 官方 PS 配置）
#   Zynq PS(官方配置) + AXI互联 + AXI GPIO + 自定义加速器(打包IP)
# 官方的 PS 配置来自板卡资料 ps7_parameters.xml（见 docs/BOARD_CONFIG.md）。
# 校验通过后再用 run_synth_gpio.tcl(l aunch_runs) 综合/实现/bitstream。
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build vivado_prj_board]
file mkdir $build_dir

create_project chain_prj $build_dir -part xc7z020clg400-1 -force

# 注册自定义加速器 IP 仓库
set_property ip_repo_paths [list [file normalize [file join $proj_root build ip_repo]]] [current_project]
update_ip_catalog -rebuild

create_bd_design "design_1"

# --- Zynq PS（先跑基础自动化，再覆盖为官方板级配置）---
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable"} [get_bd_cells ps7]
set_property -dict [list \
  CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125} \
  CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {32 Bit} \
  CONFIG.PCW_UIPARAM_DDR_SPEED_BIN {DDR3_1066F} \
  CONFIG.PCW_UIPARAM_DDR_DRAM_WIDTH {16 Bits} \
  CONFIG.PCW_UIPARAM_DDR_DEVICE_CAPACITY {4096 MBits} \
  CONFIG.PCW_UIPARAM_DDR_ECC {Disabled} \
  CONFIG.PCW_CRYSTAL_PERIPHERAL_FREQMHZ {33.333333} \
  CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} \
  CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
  CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} \
  CONFIG.PCW_UART0_UART0_IO {MIO 14 .. 15} \
  CONFIG.PCW_UART0_BAUD_RATE {115200} \
  CONFIG.PCW_UART1_PERIPHERAL_ENABLE {0} \
  CONFIG.PCW_QSPI_PERIPHERAL_ENABLE {1} \
  CONFIG.PCW_QSPI_QSPI_IO {MIO 1 .. 6} \
  CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {1} \
  CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
  CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
  CONFIG.PCW_SD0_GRP_CD_ENABLE {1} \
  CONFIG.PCW_SD0_GRP_CD_IO {MIO 10} \
  CONFIG.PCW_EN_CLK0_PORT {1} \
  CONFIG.PCW_FCLK_CLK0_FREQMHZ {100.000} \
  CONFIG.PCW_USE_M_AXI_GP0 {1} \
] [get_bd_cells ps7]

# --- AXI 互联（PS GP0 -> 2 个从机）---
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect
set_property -dict [list CONFIG.NUM_MI {2}] [get_bd_cells axi_interconnect]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_interconnect/S00_AXI]

# --- AXI GPIO（LED 反馈）---
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list CONFIG.C_GPIO_WIDTH {8}] [get_bd_cells axi_gpio_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M00_AXI] [get_bd_intf_pins axi_gpio_0/S_AXI]

# --- 自定义加速器（打包 IP，user.org:user:conv_accel_axi_lite）---
create_bd_cell -type ip -vlnv user.org:user:conv_accel_axi_lite:1.0 accel_0
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M01_AXI] [get_bd_intf_pins accel_0/S_AXI]

# --- 时钟/复位（FCLK_CLK0 / FCLK_RESET0_N）---
set clk [get_bd_pins ps7/FCLK_CLK0]
set rst [get_bd_pins ps7/FCLK_RESET0_N]
connect_bd_net $clk [get_bd_pins axi_interconnect/ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/S00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M01_ACLK]
connect_bd_net $clk [get_bd_pins ps7/M_AXI_GP0_ACLK]
connect_bd_net $clk [get_bd_pins axi_gpio_0/s_axi_aclk]
connect_bd_net $clk [get_bd_pins accel_0/S_AXI_ACLK]
connect_bd_net $rst [get_bd_pins axi_interconnect/ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/S00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M01_ARESETN]
connect_bd_net $rst [get_bd_pins axi_gpio_0/s_axi_aresetn]
connect_bd_net $rst [get_bd_pins accel_0/S_AXI_ARESETN]

# --- 地址分配 + 校验 ---
assign_bd_address
validate_bd_design
save_bd_design

puts "==== BD (BOARD) VALIDATED ===="
exit
