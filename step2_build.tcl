#=====================================================================
#  step2_build.tcl —— 综合 + 实现 + 出 bitstream
#  注意: 不删 run (delete_runs 在 2018.3 里删不掉), 直接 reset 后启动
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG  [open "D:/ubuntu_iso/step2_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== STEP2: 综合 + 实现 + 出流 ==="
L " 当前时间: [clock format [clock seconds]]"

open_project $PROJ

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " top = [get_property top [current_fileset]]  源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"
L " 现有 run: [get_runs -quiet]"

# 缺 run 就建, 有就复用
if {[llength [get_runs -quiet synth_1]] == 0} {
    L " 新建 synth_1"
    create_run synth_1 -flow "Vivado Synthesis 2018" \
        -strategy "Vivado Synthesis Defaults" -constrs [get_filesets constrs_1]
}
if {[llength [get_runs -quiet impl_1]] == 0} {
    L " 新建 impl_1"
    create_run impl_1 -flow "Vivado Implementation 2018" \
        -strategy "Vivado Implementation Defaults" -constrs [get_filesets constrs_1] -parent_run synth_1
}

# ---- 综合 ----
L ""
L ">>> reset + 综合  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st  [clock format [clock seconds]]"

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
L " ✅✅ 综合通过!  [clock format [clock seconds]]"

# ---- 实现 ----
L ""
L ">>> reset + 实现  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]  [clock format [clock seconds]]"

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
}
L "=== STEP2 结束: [clock format [clock seconds]] ==="
close $LOG
exit 0
