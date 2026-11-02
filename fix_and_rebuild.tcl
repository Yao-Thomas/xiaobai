#=====================================================================
#  fix_and_rebuild.tcl —— 修复多驱动后重新综合+实现
#  不重建工程(保留已生成好的 HLS IP 缓存), 所以【不需要改系统时间】
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set IPREPO {D:/ubuntu_iso/gpu_ip}
set LOG  [open "D:/ubuntu_iso/fixbuild_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 修复多驱动后重新构建 ==="
L " 当前时间: [clock format [clock seconds]]"

open_project $PROJ

# ---- 更新自研 GPU IP 仓库 ----
set_property ip_repo_paths [list {D:/ubuntu_iso/tmp_try2018/Navigator_7020/ip_repo} $IPREPO] [current_project]
update_ip_catalog -rebuild
L " ✅ IP 目录已更新"

open_bd_design [get_files system.bd]

# ---- 只重新生成 BD (HLS 的 IP 已是最新, 不会重跑 HLS) ----
set BDOBJ [get_files system.bd]
if {[catch {generate_target all $BDOBJ} e1]} { L " ⚠️ generate_target: $e1" }
if {[catch {validate_bd_design} e2]} { L " ❌ BD 校验失败: $e2"; close $LOG; exit 1 }
save_bd_design
L " ✅ BD 重新校验并保存"

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " 源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"

# ---- 重新综合 ----
L ""
L ">>> 综合  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st"

if {![string match "*Complete*" $st]} {
    L " RESULT=SYNTH_FAIL"
    set vds {D:/ubuntu_iso/atk2018/atk2018.runs/synth_1/system_wrapper.vds}
    if {[file exists $vds]} {
        set f [open $vds r]; set t [read $f]; close $f
        set n 0
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] && $n < 15} { L "   $line"; incr n }
        }
    }
    close $LOG
    exit 1
}
L " ✅ 综合通过"

# ---- 实现 ----
L ""
L ">>> 实现  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]"

# ---- 时序 ----
set rpt {D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/system_wrapper_timing_summary_routed.rpt}
if {[file exists $rpt]} {
    set f [open $rpt r]; set t [read $f]; close $f
    set n 0
    foreach line [split $t "\n"] {
        if {([string match "*WNS*" $line] || [string match "*Timing constraints are not met*" $line]) && $n < 4} {
            L " 时序: [string trim $line]"; incr n
        }
    }
}

set bits [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit]
if {[llength $bits] > 0} {
    foreach b $bits { L " ★★★ BITSTREAM: $b  ([file size $b] 字节)" }
    L " RESULT=OK"
} else {
    L " RESULT=IMPL_FAIL"
    set rl {D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/runme.log}
    if {[file exists $rl]} {
        set f [open $rl r]; set t [read $f]; close $f
        set n 0
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] && $n < 10} { L "   $line"; incr n }
        }
    }
}
L "=== 结束 ==="
close $LOG
exit 0
