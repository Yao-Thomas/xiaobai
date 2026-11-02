# ============================================================================
# lcd_template.xdc —— LCD 引脚约束【模板】（只服务"系统+屏幕"）
#   ⚠️ 所有 PACKAGE_PIN 都是占位符 xxx，必须按你 7 寸屏排线/正点原子工程填。
#   你把 7 寸屏排线定义给我，我帮你填好。
# ============================================================================

# ============================ LCD (RGB 并行) ============================
# 7 寸 1024x600 RGB: 24bit(R/G/B 各 8) 或 16bit(RGB565)，按屏/接线定
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[0]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[1]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[2]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[3]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[4]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[5]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[6]]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_r[7]]
# ... lcd_g[0..7], lcd_b[0..7] 同理（用 RGB565 则各 5/6/5 位）
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_pclk]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_hsync]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_vsync]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_de]
set_property -dict {PACKAGE_PIN xxx IOSTANDARD LVCMOS33} [get_ports lcd_bl]   ;# 背光使能

# ---------- 输出时钟约束 ----------
# create_clock -period 19.531 -name lcd_pclk [get_ports lcd_pclk]   ;# ~51.2MHz
# set_output_delay -clock lcd_pclk -max 2.0 [get_ports {lcd_r[*] lcd_g[*] lcd_b[*] lcd_hsync lcd_vsync lcd_de}]
# set_output_delay -clock lcd_pclk -min -2.0 [get_ports {lcd_r[*] lcd_g[*] lcd_b[*] lcd_hsync lcd_vsync lcd_de}]
