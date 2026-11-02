open_project {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set bd_file [get_files {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/system.bd}]
generate_target all $bd_file
update_compile_order -fileset sources_1
reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "AUDIO_SYNTH_STATUS: $synth_status"
if {![string match {*Complete*} $synth_status]} { error "Audio synth failed: $synth_status" }
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "AUDIO_IMPL_STATUS: $impl_status"
if {![string match {*Complete*} $impl_status]} { error "Audio implementation failed: $impl_status" }
puts "AUDIO_BIT_READY: D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/impl_1/system_wrapper.bit"
close_project
exit
