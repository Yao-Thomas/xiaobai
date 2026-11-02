#=====================================================================
#  rebuild2018.tcl —— 应用 Y2026 补丁后重新生成 IP 并出 bitstream
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG  [open "D:/ubuntu_iso/rebuild_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 应用补丁后重建  [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ
open_bd_design [get_files system.bd]

# ---- 删掉 v_frmbuf 的 IP 缓存, 强制重新生成 ----
foreach pat {*v_frmbuf_rd* *v_frmbuf_wr* *v_tc*} {
    foreach d [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/ip/$pat] {
        L " 删除缓存: [file tail $d]"
        file delete -force $d
    }
}

L ""
L ">>> generate_target all  [clock format [clock seconds]]"
set BDOBJ [get_files system.bd]
reset_target all $BDOBJ
generate_target all $BDOBJ
L " ✅ 生成完成  [clock format [clock seconds]]"

validate_bd_design
save_bd_design

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {![file exists $WFILE]} { catch {make_wrapper -files $BDOBJ -top} }
if {[file exists $WFILE] && [llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " 源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"

# ---- 综合 ----
L ""
L ">>> 综合 synth_1  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st  [clock format [clock seconds]]"

if {![string match "*Complete*" $st]} {
    L " ❌ 综合失败:"
    set vds {D:/ubuntu_iso/atk2018/atk2018.runs/synth_1/system_wrapper.vds}
    if {[file exists $vds]} {
        set f [open $vds r]; set t [read $f]; close $f
        set shown 0
        foreach line [split $t "\n"] {
            if {([string match "*ERROR*" $line] || [string match "*bad lexical*" $line]) && $shown < 12} {
                L "   $line"; incr shown
            }
        }
    }
    close $LOG
    exit 1
}
L " ✅✅ 综合通过!"

# ---- 实现 ----
L ""
L ">>> 实现 impl_1  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]"

# ---- 时序 ----
set rpt {D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/system_wrapper_timing_summary_routed.rpt}
if {[file exists $rpt]} {
    set f [open $rpt r]; set t [read $f]; close $f
    foreach line [split $t "\n"] {
        if {[string match "*WNS*" $line] || [string match "*Timing constraints are not met*" $line]} {
            L " 时序: [string trim $line]"
        }
    }
}

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit] {
    L "  ★★★ BIT: $b  ([file size $b] 字节)"
}
L " 结束: [clock format [clock seconds]]"
close $LOG
exit 0
