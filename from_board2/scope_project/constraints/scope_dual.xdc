# AX7020 peripherals retained by the oscilloscope image.

# PS EMIO GPIO. Bits 3, 7 and 10 are deliberately moved off J11 -- bits 7 and 10
# now live on J14/K14 (free pins on the J3 LCD header) because V15 and U13 are
# needed by the 3PA1030 ADC on J4.
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[0]}]
set_property -dict {PACKAGE_PIN L14 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[1]}]
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[2]}]
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[3]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[4]}]
set_property -dict {PACKAGE_PIN M19 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[5]}]
set_property -dict {PACKAGE_PIN U19 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[6]}]
set_property -dict {PACKAGE_PIN J14 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[7]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[8]}]
set_property -dict {PACKAGE_PIN G15 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[9]}]
set_property -dict {PACKAGE_PIN K14 IOSTANDARD LVCMOS33} [get_ports {gpio0_tri_io[10]}]

# LCD timing, backlight, reset and 24-bit RGB.
set_property -dict {PACKAGE_PIN P19 IOSTANDARD LVCMOS33} [get_ports lcd_clk]
set_property -dict {PACKAGE_PIN U20 IOSTANDARD LVCMOS33} [get_ports lcd_de]
set_property -dict {PACKAGE_PIN N18 IOSTANDARD LVCMOS33} [get_ports lcd_hs]
set_property -dict {PACKAGE_PIN T20 IOSTANDARD LVCMOS33} [get_ports lcd_vs]
set_property -dict {PACKAGE_PIN M20 IOSTANDARD LVCMOS33} [get_ports {lcd_bl[0]}]
set_property -dict {PACKAGE_PIN L17 IOSTANDARD LVCMOS33} [get_ports lcd_rst]
set_property -dict {PACKAGE_PIN W18 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[0]}]
set_property -dict {PACKAGE_PIN W19 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[1]}]
set_property -dict {PACKAGE_PIN R16 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[2]}]
set_property -dict {PACKAGE_PIN R17 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[3]}]
set_property -dict {PACKAGE_PIN W20 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[4]}]
set_property -dict {PACKAGE_PIN V20 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[5]}]
set_property -dict {PACKAGE_PIN P18 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[6]}]
set_property -dict {PACKAGE_PIN N17 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[7]}]
set_property -dict {PACKAGE_PIN V17 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[8]}]
set_property -dict {PACKAGE_PIN V18 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[9]}]
set_property -dict {PACKAGE_PIN T17 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[10]}]
set_property -dict {PACKAGE_PIN R18 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[11]}]
set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[12]}]
set_property -dict {PACKAGE_PIN Y19 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[13]}]
set_property -dict {PACKAGE_PIN P15 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[14]}]
set_property -dict {PACKAGE_PIN P16 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[15]}]
set_property -dict {PACKAGE_PIN V16 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[16]}]
set_property -dict {PACKAGE_PIN W16 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[17]}]
set_property -dict {PACKAGE_PIN T14 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[18]}]
set_property -dict {PACKAGE_PIN T15 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[19]}]
set_property -dict {PACKAGE_PIN Y17 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[20]}]
set_property -dict {PACKAGE_PIN Y16 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[21]}]
set_property -dict {PACKAGE_PIN T16 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[22]}]
set_property -dict {PACKAGE_PIN U17 IOSTANDARD LVCMOS33} [get_ports {lcd_rgb_tri_io[23]}]

# Ethernet PHY (direct cable/network update path retained).
set_property -dict {PACKAGE_PIN F20 IOSTANDARD LVCMOS33} [get_ports mdio_mdc]
set_property -dict {PACKAGE_PIN F19 IOSTANDARD LVCMOS33} [get_ports mdio_mdio_io]
set_property -dict {PACKAGE_PIN K17 IOSTANDARD LVCMOS33} [get_ports rgmii_rxc]
set_property -dict {PACKAGE_PIN E17 IOSTANDARD LVCMOS33} [get_ports rgmii_rx_ctl]
set_property -dict {PACKAGE_PIN B19 IOSTANDARD LVCMOS33} [get_ports {rgmii_rd[0]}]
set_property -dict {PACKAGE_PIN A20 IOSTANDARD LVCMOS33} [get_ports {rgmii_rd[1]}]
set_property -dict {PACKAGE_PIN H17 IOSTANDARD LVCMOS33} [get_ports {rgmii_rd[2]}]
set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports {rgmii_rd[3]}]
set_property -dict {PACKAGE_PIN B20 IOSTANDARD LVCMOS33} [get_ports rgmii_txc]
set_property -dict {PACKAGE_PIN K18 IOSTANDARD LVCMOS33} [get_ports rgmii_tx_ctl]
set_property -dict {PACKAGE_PIN D18 IOSTANDARD LVCMOS33} [get_ports {rgmii_td[0]}]
set_property -dict {PACKAGE_PIN C20 IOSTANDARD LVCMOS33} [get_ports {rgmii_td[1]}]
set_property -dict {PACKAGE_PIN D19 IOSTANDARD LVCMOS33} [get_ports {rgmii_td[2]}]
set_property -dict {PACKAGE_PIN D20 IOSTANDARD LVCMOS33} [get_ports {rgmii_td[3]}]
create_clock -period 8.000 -name rgmii_rxc [get_ports rgmii_rxc]

# LCD touch-controller I2C.
set_property -dict {PACKAGE_PIN R19 IOSTANDARD LVCMOS33} [get_ports i2c1_scl_io]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports i2c1_sda_io]

# =====================================================================
# 3PA1030 双路 AD —— 模块插在【J4(BANK13)扩展口】，注意【反着插】：
#   JP1 pin 1 (VCC_IN) -> J4 pin 40 (+5V)
#   JP1 pin 2 (GND)    -> J4 pin 39 (GND)
#   JP1 pin 4 (GND)    -> J4 pin 37 (GND)
#   JP1 pin 5..32      -> J4 pin 36..9
# J4 用 BANK13 + B34 摄像头那组，和 LCD(BANK34/35) 一根都不冲突。
#
# 球号 <-> B13_Lxx 是从 post_synth.dcp 的 PIN_FUNC 逐条核对出来的（不是猜的）：
#   B13_L6_N=V5  L11_N=V7 L11_P=U7  L12_N=U10 L12_P=T9  L13_N=Y6  L13_P=Y7
#   L14_N=Y8  L14_P=Y9  L15_N=W8 L15_P=V8  L16_N=W9  L16_P=W10
#   L17_N=U8  L17_P=U9  L18_N=Y11 L18_P=W11 L19_N=U5
#   L20_N=Y13 L20_P=Y12 L21_N=V10 L21_P=V11 L22_N=W6  L22_P=V6
#   B34_L3_N=V13  L4_P=V12 L4_N=W13 L8_P=W14 L8_N=Y14
#   L10_P=V15 L10_N=W15 L11_P=U14 L11_N=U15
#
# ⚠ B34_L3_P = U13 = IO_L3P_T0_DQS_PUDC_B_34 是【专用配置脚】，不能当用户 IO。
#   它落在 J4-28，也就是模块的 AD1_D9。因此 CH1 暂时用 9 位（D9 接 0）。
#   想补回第 10 位：把模块 JP1 pin13 用飞线接到空闲的 J14 即可。
# =====================================================================

# ---- 通道 1：AD1_D0..D9 = JP1 6,5,8,7,10,9,12,11,14,13 = J4 35,36,33,34,31,32,29,30,27,(28) ----
set_property -dict {PACKAGE_PIN V15 IOSTANDARD LVCMOS33} [get_ports {adc1_data[0]}]   ;# J4-35 JP1-6  D0
set_property -dict {PACKAGE_PIN W15 IOSTANDARD LVCMOS33} [get_ports {adc1_data[1]}]   ;# J4-36 JP1-5  D1
set_property -dict {PACKAGE_PIN W14 IOSTANDARD LVCMOS33} [get_ports {adc1_data[2]}]   ;# J4-33 JP1-8  D2
set_property -dict {PACKAGE_PIN Y14 IOSTANDARD LVCMOS33} [get_ports {adc1_data[3]}]   ;# J4-34 JP1-7  D3
set_property -dict {PACKAGE_PIN V12 IOSTANDARD LVCMOS33} [get_ports {adc1_data[4]}]   ;# J4-31 JP1-10 D4
set_property -dict {PACKAGE_PIN W13 IOSTANDARD LVCMOS33} [get_ports {adc1_data[5]}]   ;# J4-32 JP1-9  D5
set_property -dict {PACKAGE_PIN U14 IOSTANDARD LVCMOS33} [get_ports {adc1_data[6]}]   ;# J4-29 JP1-12 D6
set_property -dict {PACKAGE_PIN U15 IOSTANDARD LVCMOS33} [get_ports {adc1_data[7]}]   ;# J4-30 JP1-11 D7
set_property -dict {PACKAGE_PIN V13 IOSTANDARD LVCMOS33} [get_ports {adc1_data[8]}]   ;# J4-27 JP1-14 D8
set_property -dict {PACKAGE_PIN U13 IOSTANDARD LVCMOS33} [get_ports {adc1_data[9]}]   ;# J4-28 JP1-13 D9
set_property -dict {PACKAGE_PIN Y13 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports adc1_clk] ;# J4-23 JP1-18 CLK
set_property -dict {PACKAGE_PIN W11 IOSTANDARD LVCMOS33} [get_ports adc1_oe]          ;# J4-26 JP1-15 OE

# ---- 通道 2：AD2_D0..D9 = JP1 20,19,22,21,24,23,26,25,28,27 = J4 21,22,19,20,17,18,15,16,13,14 ----
set_property -dict {PACKAGE_PIN V11 IOSTANDARD LVCMOS33} [get_ports {adc2_data[0]}]   ;# J4-21 JP1-20 D0
set_property -dict {PACKAGE_PIN V10 IOSTANDARD LVCMOS33} [get_ports {adc2_data[1]}]   ;# J4-22 JP1-19 D1
set_property -dict {PACKAGE_PIN W10 IOSTANDARD LVCMOS33} [get_ports {adc2_data[2]}]   ;# J4-19 JP1-22 D2
set_property -dict {PACKAGE_PIN W9  IOSTANDARD LVCMOS33} [get_ports {adc2_data[3]}]   ;# J4-20 JP1-21 D3
set_property -dict {PACKAGE_PIN Y9  IOSTANDARD LVCMOS33} [get_ports {adc2_data[4]}]   ;# J4-17 JP1-24 D4
set_property -dict {PACKAGE_PIN Y8  IOSTANDARD LVCMOS33} [get_ports {adc2_data[5]}]   ;# J4-18 JP1-23 D5
set_property -dict {PACKAGE_PIN Y7  IOSTANDARD LVCMOS33} [get_ports {adc2_data[6]}]   ;# J4-15 JP1-26 D6
set_property -dict {PACKAGE_PIN Y6  IOSTANDARD LVCMOS33} [get_ports {adc2_data[7]}]   ;# J4-16 JP1-25 D7
set_property -dict {PACKAGE_PIN W6  IOSTANDARD LVCMOS33} [get_ports {adc2_data[8]}]   ;# J4-13 JP1-28 D8
set_property -dict {PACKAGE_PIN V6  IOSTANDARD LVCMOS33} [get_ports {adc2_data[9]}]   ;# J4-14 JP1-27 D9
set_property -dict {PACKAGE_PIN U9  IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports adc2_clk] ;# J4-9  JP1-32 CLK
set_property -dict {PACKAGE_PIN T9  IOSTANDARD LVCMOS33} [get_ports adc2_oe]          ;# J4-12 JP1-29 OE

# The ADC has up to 25 ns clock-to-data delay relative to the forwarded
# 20 MHz clock. Vivado 2018.3 XDC files do not accept Tcl "if" commands, so
# bind the delay directly to the generated clock created by scope_adc_clk.
set_input_delay -clock [get_clocks clk_out1_system_scope_adc_clk_0] -max 25.000 [get_ports {adc1_data[*] adc2_data[*]}]
set_input_delay -clock [get_clocks clk_out1_system_scope_adc_clk_0] -min 0.000  [get_ports {adc1_data[*] adc2_data[*]}]

# ============================================================================
# 包络 BRAM 的跨时钟域约束（阶段4）
#
# 包络 BRAM 的写口在 sample_clk（clk_out2, 20MHz），读口在 AXI 时钟
# （clk_fpga_0, 100MHz）。两个时钟同源（都来自 scope_adc_clk 的 MMCM），
# 但相位不同，工具会按最紧的 setup 关系检查：
#     实测 requirement 2.500ns，data path delay 3.306ns，违例 -0.229ns。
#
# 这条路径是合法的 CDC：包络数据【整帧不变】，PS 以帧为节奏读取，
# 相对 20MHz 采集时钟是准静态的。因此用 datapath_only 把它放宽到远大于
# 实际数据变化率的 12ns —— 既消除假违例，又仍然约束住真实延迟，
# 不像 set_false_path 那样完全放弃检查。
# 注意：只约束 env_rd_data 这一个目的寄存器，不影响其它跨时钟路径。
# ============================================================================
set_max_delay -datapath_only 12.000 \
    -from [get_clocks clk_out2_system_scope_adc_clk_0] \
    -to   [get_cells -hierarchical -filter {NAME =~ *capture_core/env_rd_data_reg*}] \
    -quiet
