# ============================================================================
# run_bd.tcl —— 第 1 步：创建 Zynq + AXI 互联 + GPIO + 自定义加速器的 Block Design
# 并校验。确认无误后再用 run_synth.tcl 做综合/实现/bitstream。
# 验证：CPU(PS) -> AXI Interconnect -> (axi_gpio / conv_accel_axi_lite 从机)
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set rtl_src     [file join $proj_root src rtl]
set build_dir   [file join $proj_root build vivado_prj]

file mkdir $build_dir

# --- 创建工程（project 模式）---
create_project chain_prj $build_dir -part xc7z020clg400-1 -force

# --- 注册自定义 IP 仓库（打包的 conv_accel_axi_lite）---
set_property ip_repo_paths [list [file normalize [file join $proj_root build ip_repo]]] [current_project]
update_ip_catalog -rebuild

# --- 创建 Block Design ---
create_bd_design "design_1"

# --- Zynq PS ---
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable"} [get_bd_cells ps7]
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1}] [get_bd_cells ps7]

# --- AXI 互联（PS GP0 -> 2 个从端口）---
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect
set_property -dict [list CONFIG.NUM_MI {2}] [get_bd_cells axi_interconnect]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_interconnect/S00_AXI]

# --- AXI GPIO（LED 反馈）---
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list CONFIG.C_GPIO_WIDTH {8}] [get_bd_cells axi_gpio_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M00_AXI] [get_bd_intf_pins axi_gpio_0/S_AXI]

# --- 自定义加速器从机（MAC 计算核，打包 IP）---
create_bd_cell -type ip -vlnv user.org:user:conv_accel_axi_lite:1.0 accel_0
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M01_AXI] [get_bd_intf_pins accel_0/S_AXI]

# --- 时钟与复位连接（统一使用 FCLK_CLK0 / FCLK_RESET0_N）---
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

# --- 地址自动分配（把从机地址段映射进 ps7/Data，供 PS 访问）---
assign_bd_address

# --- 校验 ---
validate_bd_design
save_bd_design

puts "==== BD VALIDATED ===="
exit
