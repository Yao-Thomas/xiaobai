# ============================================================================
# run_synth_gpio.tcl —— 用 Vivado 工程 run 流做综合+实现+bitstream（自动触发 IP OOC）
# 前置：run_bd_gpio.tcl 已建好并校验 Block Design。
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build vivado_prj_gpio]
set board_dir   [file join $proj_root board]
file mkdir $board_dir

open_project [file join $build_dir chain_prj.xpr]

make_wrapper -files [get_files design_1.bd] -top
add_files -fileset sources_1 -norecurse [file join $build_dir chain_prj.srcs sources_1 bd design_1 hdl design_1_wrapper.v]
set_property top design_1_wrapper [get_filesets sources_1]
update_compile_order -fileset sources_1

puts "==== [clock format [clock seconds]] LAUNCH synth_1 ===="
launch_runs -jobs 8 synth_1
wait_on_run synth_1
open_run synth_1

puts "==== [clock format [clock seconds]] LAUNCH impl_1 ===="
launch_runs -jobs 8 impl_1
wait_on_run impl_1
open_run impl_1

puts "==== [clock format [clock seconds]] write_bitstream ===="
write_bitstream -force [file join $board_dir chain.bit]
write_hw_platform -fixed -include_bit -force [file join $board_dir chain.hdf]

puts "==== VIVADO BUILD DONE ===="
exit
