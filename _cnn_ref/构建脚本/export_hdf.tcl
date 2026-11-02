# ============================================================================
# export_hdf.tcl —— 打开已实现的设计并导出硬件平台(.hdf)，供 SDK 建 BSP
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build vivado_prj_gpio]
set board_dir   [file join $proj_root board]
file mkdir $board_dir

open_project [file join $build_dir chain_prj.xpr]
open_run impl_1
write_hw_platform -fixed -include_bit [file join $board_dir chain.hdf]
puts "==== HDF EXPORTED ===="
exit
