open_project {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
open_bd_design {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/system.bd}

# The ES8388 BCLK must come from a single I2S clock generator. The original
# block design ORs the independent TX/RX SCLK outputs, corrupting clock edges.
set tx [get_bd_pins /audio/i2s_transmitter/sclk_out]
set bclk [get_bd_pins /audio/aud_bclk]
set rx [get_bd_pins /audio/i2s_receiver/sclk_out]
set combiner [get_bd_cells /audio/util_vector_logic_0]
puts "BEFORE_TX_NET: [get_bd_nets -of_objects $tx]"
puts "BEFORE_RX_NET: [get_bd_nets -of_objects $rx]"
puts "BEFORE_BCLK_NET: [get_bd_nets -of_objects $bclk]"

delete_bd_objs $combiner
connect_bd_net $tx $bclk
puts "AFTER_TX_NET: [get_bd_nets -of_objects $tx]"
puts "AFTER_BCLK_NET: [get_bd_nets -of_objects $bclk]"
puts "FORMATTER_MODE: [get_property CONFIG.C_MM2S_DATAFORMAT [get_bd_cells /audio/audio_formatter]]"
validate_bd_design
save_bd_design

set bd_file [get_files {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/system.bd}]
generate_target all $bd_file
update_compile_order -fileset sources_1
puts "AUDIO_CLOCK_FIX_SAVED"
close_project
exit
