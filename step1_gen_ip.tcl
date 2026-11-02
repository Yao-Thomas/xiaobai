#=====================================================================
#  step1_gen_ip.tcl —— 第一步: 在【2020 年】环境下生成 IP
#  这一步会调用 HLS 打包 IP, 也就是踩到 core_revision 溢出的地方
#=====================================================================
set ATK  {D:/ubuntu_iso/tmp_try2018/Navigator_7020}
set NEW  {D:/ubuntu_iso/atk2018}
set LOG  [open "D:/ubuntu_iso/step1_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== STEP1: 生成 IP (需要系统时间 <= 2021) ==="
L " 当前时间: [clock format [clock seconds]]"

if {[file exists $NEW]} { file delete -force $NEW }
create_project -force atk2018 $NEW -part xc7z020clg400-2
set_property ip_repo_paths [list $ATK/ip_repo {D:/ubuntu_iso/gpu_ip}] [current_project]
update_ip_catalog -rebuild

# 复制 BD 到工程原生位置
set dstbd $NEW/atk2018.srcs/sources_1/bd/system
file mkdir $dstbd
foreach item [glob -nocomplain $ATK/Navigator_7020.srcs/sources_1/bd/system/*] {
    if {[file tail $item] eq "system.bd.orig"} { continue }
    file copy -force $item $dstbd/[file tail $item]
}
set BDFILE $dstbd/system.bd
add_files -norecurse $BDFILE
add_files -fileset constrs_1 -norecurse $ATK/Navigator_7020.srcs/constrs_1/system.xdc
update_compile_order -fileset sources_1
open_bd_design $BDFILE

set BDOBJ [get_files system.bd]
reset_target all $BDOBJ
generate_target all $BDOBJ
L " ✅ generate_target 完成: [clock format [clock seconds]]"

# 检查那两个要命的 IP 有没有真的生成出来
set ok 1
foreach ip {system_v_frmbuf_rd_0_0 system_v_frmbuf_rd_0_1 system_v_frmbuf_wr_0_0} {
    set d $NEW/atk2018.srcs/sources_1/bd/system/ip/$ip
    set n 0
    if {[file exists $d]} { set n [llength [glob -nocomplain $d/*]] }
    L "   $ip : $n 项"
    if {$n < 5} { set ok 0 }
}

set WFILE $dstbd/hdl/system_wrapper.v
if {![file exists $WFILE]} { catch {make_wrapper -files $BDOBJ -top} }
if {[file exists $WFILE] && [llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
close_project

if {$ok} {
    L " RESULT=OK"
} else {
    L " RESULT=FAIL (有 IP 没生成全)"
}
L "=== STEP1 结束 ==="
close $LOG
exit 0
