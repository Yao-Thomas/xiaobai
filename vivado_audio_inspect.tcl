open_project {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
open_bd_design {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/system.bd}
puts "AUDIO_BD_PORTS: [get_bd_pins -quiet /audio/aud_bclk]"
puts "AUDIO_TX_SCLK: [get_bd_pins -quiet /audio/i2s_transmitter/sclk_out]"
puts "AUDIO_RX_SCLK: [get_bd_pins -quiet /audio/i2s_receiver/sclk_out]"
puts "AUDIO_OR_CELL: [get_bd_cells -quiet /audio/util_vector_logic_0]"
puts "AUDIO_FORMATTER_CELL: [get_bd_cells -quiet /audio/audio_formatter]"
puts "AUDIO_FORMATTER_MODE: [get_property CONFIG.C_MM2S_DATAFORMAT [get_bd_cells /audio/audio_formatter]]"
puts "AUDIO_BITSTREAM_STATUS: [get_property STATUS [get_runs impl_1]]"
close_project
exit
