# ============================================================================
# run_hls_synth.tcl —— HLS 综合 + 导出 IP（含 solution 配置）
# 目标器件：XC7Z020（正点原子 ZYNQ7020）
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]

set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj]
set ip_out       [file join $proj_root build ip]

file mkdir $build_dir
file mkdir $ip_out

cd $build_dir
open_project -reset conv2d_prj
set_top conv2d
add_files -cflags "-std=c++11" [file join $hls_src conv2d.cpp]
add_files -tb   [file join $hls_src conv2d_tb.cpp]

# --- 打开/新建 solution 并配置目标器件与时钟 ---
open_solution -reset sol1
set_part xc7z020clg400-1
create_clock -period 10 -name default

puts "==== [clock format [clock seconds]] CSYNTH start ===="
csynth_design

puts "==== [clock format [clock seconds]] EXPORT start ===="
export_design -format ip_catalog -ipname conv2d_v1_0 -vendor "user.org" -library "user" -version "1.0"

puts "==== HLS DONE ===="
exit
