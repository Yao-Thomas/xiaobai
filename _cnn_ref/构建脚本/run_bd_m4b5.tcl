# run_bd_m4b5.tcl —— M4b-5：PS + cnn_conv_pool_q + cnn_fc_q (6 个 m_axi -> S_AXI_HP0)
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build vivado_prj_m4b5]
file mkdir $build_dir
create_project chain_prj $build_dir -part xc7z020clg400-1 -force
set_property ip_repo_paths [list [file normalize [file join $proj_root build ip_repo_cpq]] [file normalize [file join $proj_root build ip_repo_fcq]]] [current_project]
update_ip_catalog -rebuild
create_bd_design "design_1"
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable"} [get_bd_cells ps7]
set_property -dict [list \
  CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125} \
  CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {32 Bit} \
  CONFIG.PCW_UIPARAM_DDR_SPEED_BIN {DDR3_1066F} \
  CONFIG.PCW_UIPARAM_DDR_DRAM_WIDTH {16 Bits} \
  CONFIG.PCW_UIPARAM_DDR_DEVICE_CAPACITY {4096 MBits} \
  CONFIG.PCW_CRYSTAL_PERIPHERAL_FREQMHZ {33.333333} \
  CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} \
  CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
  CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} \
  CONFIG.PCW_UART0_UART0_IO {MIO 14 .. 15} \
  CONFIG.PCW_UART0_BAUD_RATE {115200} \
  CONFIG.PCW_QSPI_PERIPHERAL_ENABLE {1} \
  CONFIG.PCW_QSPI_QSPI_IO {MIO 1 .. 6} \
  CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
  CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
  CONFIG.PCW_EN_CLK0_PORT {1} \
  CONFIG.PCW_USE_M_AXI_GP0 {1} \
  CONFIG.PCW_USE_S_AXI_HP0 {1} \
] [get_bd_cells ps7]

# GP0 互联：GPIO + cpq + fcq (3 从机)
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect
set_property -dict [list CONFIG.NUM_MI {3}] [get_bd_cells axi_interconnect]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_interconnect/S00_AXI]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list CONFIG.C_GPIO_WIDTH {8}] [get_bd_cells axi_gpio_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M00_AXI] [get_bd_intf_pins axi_gpio_0/S_AXI]

create_bd_cell -type ip -vlnv user.org:user:cnn_conv_pool_q:1.0 cpq_0
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M01_AXI] [get_bd_intf_pins cpq_0/S_AXI_AXILiteS]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins cpq_0/m_axi_gmem_img]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins cpq_0/m_axi_gmem_w]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins cpq_0/m_axi_gmem_out]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins cpq_0/s_axi_AXILiteS]

create_bd_cell -type ip -vlnv user.org:user:cnn_fc_q:1.0 fcq_0
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M02_AXI] [get_bd_intf_pins fcq_0/S_AXI_AXILiteS]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins fcq_0/m_axi_gmem_x]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins fcq_0/m_axi_gmem_w]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins fcq_0/m_axi_gmem_out]
set_property CONFIG.FREQ_HZ 50000000 [get_bd_intf_pins fcq_0/s_axi_AXILiteS]

# HP 互联：6 个 m_axi 主 -> HP0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_hp
set_property -dict [list CONFIG.NUM_MI {1} CONFIG.NUM_SI {6}] [get_bd_cells axi_hp]
connect_bd_intf_net [get_bd_intf_pins cpq_0/M_AXI_gmem_img] [get_bd_intf_pins axi_hp/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins cpq_0/M_AXI_gmem_w]   [get_bd_intf_pins axi_hp/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins cpq_0/M_AXI_gmem_out] [get_bd_intf_pins axi_hp/S02_AXI]
connect_bd_intf_net [get_bd_intf_pins fcq_0/M_AXI_gmem_x]   [get_bd_intf_pins axi_hp/S03_AXI]
connect_bd_intf_net [get_bd_intf_pins fcq_0/M_AXI_gmem_w]   [get_bd_intf_pins axi_hp/S04_AXI]
connect_bd_intf_net [get_bd_intf_pins fcq_0/M_AXI_gmem_out] [get_bd_intf_pins axi_hp/S05_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_hp/M00_AXI] [get_bd_intf_pins ps7/S_AXI_HP0]

# 时钟/复位
set clk [get_bd_pins ps7/FCLK_CLK0]
set rst [get_bd_pins ps7/FCLK_RESET0_N]
connect_bd_net $clk [get_bd_pins axi_interconnect/ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/S00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M01_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M02_ACLK]
connect_bd_net $clk [get_bd_pins cpq_0/ap_clk]
connect_bd_net $clk [get_bd_pins fcq_0/ap_clk]
connect_bd_net $clk [get_bd_pins axi_gpio_0/s_axi_aclk]
connect_bd_net $clk [get_bd_pins axi_hp/ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S00_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S01_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S02_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S03_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S04_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S05_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/M00_ACLK]
connect_bd_net $clk [get_bd_pins ps7/M_AXI_GP0_ACLK]
connect_bd_net $clk [get_bd_pins ps7/S_AXI_HP0_ACLK]
connect_bd_net $rst [get_bd_pins axi_interconnect/ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/S00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M01_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M02_ARESETN]
connect_bd_net $rst [get_bd_pins cpq_0/ap_rst_n]
connect_bd_net $rst [get_bd_pins fcq_0/ap_rst_n]
connect_bd_net $rst [get_bd_pins axi_gpio_0/s_axi_aresetn]
connect_bd_net $rst [get_bd_pins axi_hp/ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S01_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S02_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S03_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S04_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S05_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/M00_ARESETN]

assign_bd_address
validate_bd_design
save_bd_design
puts "==== BD (M4B5) VALIDATED ===="
exit
