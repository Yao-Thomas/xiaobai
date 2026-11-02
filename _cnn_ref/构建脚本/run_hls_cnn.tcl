# ============================================================================
# run_hls_cnn.tcl —— M4b-1：CNN 单通道 3x3 卷积（m_axi 数据通路）综合 + 导出 IP
# 目标器件：XC7Z020（正点原子 ZYNQ7020）
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]

set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj_cnn]
set ip_out       [file join $proj_root build ip_cnn]

file mkdir $build_dir
file mkdir $ip_out

cd $build_dir
open_project -reset cnn_prj
set_top cnn_conv1
add_files -cflags "-std=c++11" [file join $hls_src cnn_conv.cpp]

open_solution -reset sol1
set_part xc7z020clg400-1
create_clock -period 10 -name default

puts "==== [clock format [clock seconds]] CSYNTH start ===="
csynth_design

puts "==== [clock format [clock seconds]] EXPORT start ===="
export_design -format ip_catalog -ipname cnn_conv1_v1_0 -vendor "user.org" -library "user" -version "1.0"

puts "==== HLS CNN DONE ===="
exit
