# ============================================================================
# run_synth.tcl —— 第 2 步：综合 + 实现 + 生成比特流 + 导硬件平台(.hdf)
# 前置：run_bd.tcl 已成功创建并校验 Block Design。
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build vivado_prj]
set board_dir   [file join $proj_root board]
file mkdir $board_dir

open_project [file join $build_dir chain_prj.xpr]

# --- 生成 Block Design 的 HDL wrapper 并设为顶层 ---
make_wrapper -files [get_files design_1.bd] -top
add_files -fileset sources_1 -norecurse [file join $build_dir chain_prj.srcs sources_1 bd design_1 hdl design_1_wrapper.v]
set_property top design_1_wrapper [get_filesets sources_1]
update_compile_order -fileset sources_1
# 生成 BD 全部输出产物
generate_target all [get_files design_1.bd]

# --- 综合 ---
puts "==== [clock format [clock seconds]] SYNTH start ===="
synth_design -top design_1_wrapper -part xc7z020clg400-1

# --- 实现 ---
puts "==== [clock format [clock seconds]] OPT start ===="
opt_design
place_design
phys_opt_design
route_design

# --- 生成比特流 ---
puts "==== [clock format [clock seconds]] BITSTREAM start ===="
write_bitstream -force [file join $board_dir chain.bit]

# --- 导出硬件平台（供 SDK/裸机 BSP 使用；2018.3 为 .hdf）---
write_hw_platform -fixed -include_bit -force [file join $board_dir chain.hdf]

puts "==== VIVADO BUILD DONE ===="
exit
