# run_hls_cnn2.tcl —— M4b-2：Conv1+ReLU+MaxPool 综合（生成 RTL，打包交给 ipx，规避 core_revision）
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]

set hls_src      [file join $proj_root src hls]
set build_dir    [file join $proj_root build hls_prj_cnn2]

file mkdir $build_dir

cd $build_dir
open_project -reset cnn2_prj
set_top cnn_conv1_pool
add_files -cflags "-std=c++11" [file join $hls_src cnn_conv1_pool.cpp]

open_solution -reset sol1
set_part xc7z020clg400-1
create_clock -period 10 -name default

puts "==== [clock format [clock seconds]] CSYNTH start ===="
csynth_design

puts "==== [clock format [clock seconds]] EXPORT start ===="
# export 会因 core_revision 在最终打包处失败；但 RTL 已写入 sol1/impl/ip，供 ipx 使用
export_design -format ip_catalog -ipname cnn_conv1_pool_v1_0 -vendor "user.org" -library "user" -version "1.0"

puts "==== HLS CNN2 DONE (export may warn about core_revision) ===="
exit
