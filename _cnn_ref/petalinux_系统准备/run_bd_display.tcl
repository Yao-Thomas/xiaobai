# ============================================================================
# run_bd_display.tcl —— P2 起点脚本：Zynq PS + 显示流水线(VDMA + v_tc + v_axi4s_vid_out)
#   ⚠️ 这是"起点参考"，不是成品：
#      - PS7 配置与我们所有工程一致（可直接复用，已验证）。
#      - 显示 IP 的视频接口连线/位宽/时序、LCD 引脚约束，必须按 7 寸 1024x600 屏
#        与正点原子《领航者 ZYNQ Linux 开发指南》配套工程补全后再综合。
#   用法：vivado -mode batch -source run_bd_display.tcl
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set build_dir  [file join $script_dir vivado_prj_display]
file mkdir $build_dir
create_project chain_prj $build_dir -part xc7z020clg400-1 -force
create_bd_design "design_1"

# ---------- Zynq PS（官方板级配置，与我们裸机工程一致）----------
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

# ---------- GP0 从机互联（NUM_MI>=2 铁律；先给 VDMA/v_tc/GPIO）----------
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect
set_property -dict [list CONFIG.NUM_MI {3}] [get_bd_cells axi_interconnect]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_interconnect/S00_AXI]

# AXI GPIO：LCD 背光/使能
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_lcd
set_property -dict [list CONFIG.C_GPIO_WIDTH {8} CONFIG.C_GPIO2_WIDTH {8} \
                         CONFIG.C_IS_DUAL {1}] [get_bd_cells axi_gpio_lcd]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M00_AXI] [get_bd_intf_pins axi_gpio_lcd/S_AXI]

# ---------- 显示流水线 IP ----------
# AXI VDMA：DDR 帧缓冲 <-> AXI4-Stream（MM2S 读给显示；S2MM 写收采集数据）
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 axi_vdma_0
set_property -dict [list \
  CONFIG.c_include_s2mm {1} \
  CONFIG.c_m_axi_mm2s_data_width {64} \
  CONFIG.c_m_axis_mm2s_tdata_width {32} \
  CONFIG.c_m_axi_s2mm_data_width {64} \
  CONFIG.c_s_axis_s2mm_tdata_width {32} \
  CONFIG.c_num_fstores {3} \
] [get_bd_cells axi_vdma_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M01_AXI] [get_bd_intf_pins axi_vdma_0/S_AXI_LITE]

# Video Timing Controller：产生 1024x600 显示时序
create_bd_cell -type ip -vlnv xilinx.com:ip:v_tc:6.2 v_tc_0
set_property -dict [list CONFIG.enable_detection {false}] [get_bd_cells v_tc_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M02_AXI] [get_bd_intf_pins v_tc_0/ctrl]

# AXI4-Stream to Video Out：Stream -> 并行视频
create_bd_cell -type ip -vlnv xilinx.com:ip:v_axi4s_vid_out:4.0 v_axi4s_vid_out_0
set_property -dict [list CONFIG.C_HAS_ASYNC_CLK {1}] [get_bd_cells v_axi4s_vid_out_0]

# ---------- 视频接口连线（起点；按正点原子工程核对）----------
connect_bd_intf_net [get_bd_intf_pins axi_vdma_0/M_AXIS_MM2S]     [get_bd_intf_pins v_axi4s_vid_out_0/video_in]
connect_bd_intf_net [get_bd_intf_pins v_tc_0/vtiming_out]         [get_bd_intf_pins v_axi4s_vid_out_0/vtiming_in]

# ---------- VDMA 主口 -> HP0（直读/写 DDR，与 CNN 加速器同一思路）----------
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_hp
set_property -dict [list CONFIG.NUM_MI {1} CONFIG.NUM_SI {2}] [get_bd_cells axi_hp]
connect_bd_intf_net [get_bd_intf_pins axi_vdma_0/M_AXI_MM2S] [get_bd_intf_pins axi_hp/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_vdma_0/M_AXI_S2MM] [get_bd_intf_pins axi_hp/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_hp/M00_AXI] [get_bd_intf_pins ps7/S_AXI_HP0]

# ---------- 时钟/复位 ----------
set clk [get_bd_pins ps7/FCLK_CLK0]
set rst [get_bd_pins ps7/FCLK_RESET0_N]
connect_bd_net $clk [get_bd_pins axi_interconnect/ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/S00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M00_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M01_ACLK]
connect_bd_net $clk [get_bd_pins axi_interconnect/M02_ACLK]
connect_bd_net $clk [get_bd_pins axi_gpio_lcd/s_axi_aclk]
connect_bd_net $clk [get_bd_pins axi_vdma_0/s_axi_lite_aclk]
connect_bd_net $clk [get_bd_pins axi_vdma_0/m_axi_mm2s_aclk]
connect_bd_net $clk [get_bd_pins axi_vdma_0/m_axi_s2mm_aclk]
connect_bd_net $clk [get_bd_pins v_tc_0/s_axi_aclk]
connect_bd_net $clk [get_bd_pins v_axi4s_vid_out_0/aclk]
connect_bd_net $clk [get_bd_pins axi_hp/ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S00_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/S01_ACLK]
connect_bd_net $clk [get_bd_pins axi_hp/M00_ACLK]
connect_bd_net $clk [get_bd_pins ps7/M_AXI_GP0_ACLK]
connect_bd_net $clk [get_bd_pins ps7/S_AXI_HP0_ACLK]
connect_bd_net $rst [get_bd_pins axi_interconnect/ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/S00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M01_ARESETN]
connect_bd_net $rst [get_bd_pins axi_interconnect/M02_ARESETN]
connect_bd_net $rst [get_bd_pins axi_gpio_lcd/s_axi_aresetn]
connect_bd_net $rst [get_bd_pins axi_vdma_0/axi_resetn]
connect_bd_net $rst [get_bd_pins v_tc_0/s_axi_aresetn]
connect_bd_net $rst [get_bd_pins axi_hp/ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S00_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/S01_ARESETN]
connect_bd_net $rst [get_bd_pins axi_hp/M00_ARESETN]

assign_bd_address
validate_bd_design
save_bd_design
puts "==== BD (DISPLAY 起点) 已保存；请补全 LCD 引脚/时序/video 时钟后再综合 ===="
exit
