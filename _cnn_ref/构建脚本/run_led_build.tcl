# ============================================================================
# run_led_build.tcl —— M1：纯 PL LED 闪烁 综合/实现/bitstream
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set build_dir   [file join $proj_root build led_prj]
set board_dir   [file join $proj_root board]
file mkdir $build_dir
file mkdir $board_dir

create_project led_prj $build_dir -part xc7z020clg400-1 -force
add_files [file join $proj_root src rtl led_blink.v]
add_files -fileset constrs_1 [file join $proj_root src rtl led_blink.xdc]
set_property top led_blink [get_filesets sources_1]
update_compile_order -fileset sources_1

puts "==== [clock format [clock seconds]] SYNTH ===="
synth_design -top led_blink -part xc7z020clg400-1
puts "==== [clock format [clock seconds]] IMPL ===="
opt_design
place_design
route_design
puts "==== [clock format [clock seconds]] BITSTREAM ===="
write_bitstream -force [file join $board_dir led_blink.bit]
puts "==== LED BUILD DONE ===="
exit
