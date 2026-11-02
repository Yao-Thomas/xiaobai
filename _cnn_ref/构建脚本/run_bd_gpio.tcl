# ============================================================================
# run_bd_gpio.tcl —— 第 1 步（保证可综合版）：Zynq PS + AXI 互联 + AXI GPIO
# 目的：产出可用的 bitstream + HDF，证明 CPU(PS)-AXI-PL 硬件链路可跑通。
# 说明：自定义 NPU 加速器（conv_accel_axi_lite）因 headless 下 IP 综合的
#       已知问题暂不入本次 build，其功能由 sim/tb_conv_accel.v 仿真验证（M5）。
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build vivado_prj_gpio]
file mkdir $build_dir

create_project chain_prj $build_dir -part xc7z020clg400-1 -force

create_bd_design "design_1"

# --- Zynq PS ---
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable"} [get_bd_cells ps7]
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1}] [get_bd_cells ps7]

# --- AXI 互联（PS GP0 -> 1 个从端口）---
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect
set_property -dict [list CONFIG.NUM_MI {1}] [get_bd_cells axi_interconnect]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_interconnect/S00_AXI]

# --- AXI GPIO（LED 反馈）---
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list CONFIG.C_GPIO_WIDTH {8}] [get_bd_cells axi_gpio_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M00_AXI] [get_bd_intf_pins axi_gpio_0/S_AXI]

# --- 时钟/复位 ---
set clk [get_bd_pins ps7/FCLK_CLK0]
set rst [get_bd_pins ps7/FCLK_RESET0_N]
connect_bd_net $clk [get_bd_pins axi_interconnect/ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/S00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M00_ACLK]
connect_bd_net $clk [get_bd_pins ps7/M_AXI_GP0_ACLK]
connect_bd_net $clk [get_bd_pins axi_gpio_0/s_axi_aclk]
connect_bd_net $rst [get_bd_pins axi_interconnect/ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/S00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_gpio_0/s_axi_aresetn]

assign_bd_address
validate_bd_design
save_bd_design

puts "==== BD (GPIO) VALIDATED ===="
exit
