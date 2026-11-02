# run_hls_fc.tcl —— M4b-4 全连接层综合
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj_fc]
file mkdir $build_dir
cd $build_dir
open_project -reset fc_prj
set_top cnn_fc
add_files -cflags "-std=c++11" [file join $hls_src cnn_fc.cpp]
open_solution -reset sol1
set_part xc7z020clg400-1
create_clock -period 10 -name default
puts "==== CSYNTH ===="
csynth_design
puts "==== EXPORT ===="
export_design -format ip_catalog -ipname cnn_fc_v1_0 -vendor "user.org" -library "user" -version "1.0"
puts "==== HLS FC DONE ===="
exit
