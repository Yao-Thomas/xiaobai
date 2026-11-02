# run_hls_cnn3.tcl —— M4b-3：通用 Conv+ReLU+MaxPool 综合（RTL 供 ipx 打包）
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj_cnn3]
file mkdir $build_dir
cd $build_dir
open_project -reset cnn3_prj
set_top cnn_conv_pool
add_files -cflags "-std=c++11" [file join $hls_src cnn_conv_pool.cpp]
open_solution -reset sol1
set_part xc7z020clg400-1
create_clock -period 10 -name default
puts "==== CSYNTH start ===="
csynth_design
puts "==== EXPORT start ===="
export_design -format ip_catalog -ipname cnn_conv_pool_v1_0 -vendor "user.org" -library "user" -version "1.0"
puts "==== HLS CNN3 DONE ===="
exit
