# run_hls_cnn3_cosim.tcl —— M4b-3：cnn_conv_pool 协同仿真（复现 ch15 问题）
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj_cnn3]
file mkdir $build_dir
cd $build_dir
open_project -reset cnn3_prj
set_top cnn_conv_pool
add_files -cflags "-std=c++14" [file join $hls_src cnn_conv_pool.cpp]
add_files -tb -cflags "-std=c++14" [file join $hls_src cnn_conv_pool_tb.cpp]
add_files -tb    [file join $hls_src conv2_test.h]
open_solution -reset sol1
set_part xc7z020clg400-1
create_clock -period 10 -name default
puts "==== CSIM start (C model sanity) ===="
csim_design -clean
puts "==== CSYNTH ===="
csynth_design
puts "==== COSIM start (RTL vs C tb) ===="
cosim_design -argv { } -trace_level none
puts "==== HLS CNN3 COSIM DONE ===="
exit
