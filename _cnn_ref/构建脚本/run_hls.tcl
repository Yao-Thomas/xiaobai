# ============================================================================
# run_hls.tcl —— Vitis HLS 2018.3 一键：C仿真 -> 综合 -> 导出 IP
# 位置：build/run_hls.tcl   （相对本脚本定位，跨目录可复现）
# 用法：vivado_hls -f build/run_hls.tcl
# 注意：Windows 上 open_project 不接受带盘符冒号的完整路径，须先 cd 再用纯工程名。
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]

set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj]
set ip_out       [file join $proj_root build ip]

file mkdir $build_dir
file mkdir $ip_out

# --- 1) 建立工程（先 cd 到目录，用纯工程名）---
cd $build_dir
open_project -reset conv2d_prj
set_top conv2d
add_files -cflags "-std=c++11" [file join $hls_src conv2d.cpp]
add_files -tb   [file join $hls_src conv2d_tb.cpp]

# --- 2) C 仿真（主机验证逻辑正确性）---
puts "==== [clock format [clock seconds]] CSIM start ===="
csim_design -clean

# --- 3) HLS 综合（C++ -> RTL）---
puts "==== [clock format [clock seconds]] CSYNTH start ===="
csynth_design

# --- 4) 导出为 AXI 封装 IP（供 Block Design 使用）---
puts "==== [clock format [clock seconds]] EXPORT start ===="
export_design -format ip_catalog -output [file join $ip_out conv2d_ip.zip]

puts "==== HLS DONE ===="
exit
