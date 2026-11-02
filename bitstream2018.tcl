#=====================================================================
#  bitstream2018.tcl —— 生成 bitstream (综合 + 实现 + 写流)
#  在后台运行, 约 30-60 分钟
#=====================================================================
set LOG [open "D:/ubuntu_iso/bitstream_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 生成 bitstream (Vivado [version -short])"
L " 开始: [clock format [clock seconds]]"
L "======================================================"

open_project {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.xpr}
open_bd_design [get_files system.bd]

# ---- 生成 BD 的 wrapper ----
set bdfile [get_files system.bd]
# make_wrapper 会把 wrapper 写到 BD 所在目录
set WDIR {D:/ubuntu_iso/tmp_try2018/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/hdl}
set WFILE $WDIR/system_wrapper.v

if {![file exists $WFILE]} {
    L " 生成 wrapper ..."
    if {[catch {make_wrapper -files $bdfile -top} werr]} {
        L " ⚠️ make_wrapper: $werr"
    }
} else {
    L " wrapper 已存在: $WFILE"
}

if {![file exists $WFILE]} {
    L " ❌ wrapper 仍未生成, 中止"
    close $LOG
    exit 1
}
L " wrapper: $WFILE ([file size $WFILE] 字节)"

if {[llength [get_files -quiet $WFILE]] == 0} {
    add_files -norecurse $WFILE
    L " ✅ wrapper 已加入工程"
}
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " top = [get_property top [current_fileset]]"

# 确认顶层模块能被找到
if {[llength [get_files -quiet *system_wrapper.v]] == 0} {
    L " ❌ 工程里没有 system_wrapper.v, 中止"
    close $LOG
    exit 1
}

# ---- 综合 ----
L ""
L ">>> 开始综合 synth_1  ([clock format [clock seconds]])"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
set pr [get_property PROGRESS [get_runs synth_1]]
L " synth_1: $pr  $st  ([clock format [clock seconds]])"
if {![string match "*Complete*" $st]} {
    L " ❌ 综合失败! 详见 runme.log"
    set rl D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/synth_1/runme.log
    if {[file exists $rl]} {
        set f [open $rl r]
        set tail [read $f]
        close $f
        L " --- runme.log 末尾 ---"
        foreach line [lrange [split $tail "\n"] end-25 end] { L "  $line" }
    }
    close $LOG
    exit 1
}

# ---- 实现 + 写 bitstream ----
L ""
L ">>> 开始实现 impl_1  ([clock format [clock seconds]])"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
set st2 [get_property STATUS [get_runs impl_1]]
set pr2 [get_property PROGRESS [get_runs impl_1]]
L " impl_1: $pr2  $st2  ([clock format [clock seconds]])"

# ---- 结果 ----
L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/impl_1/*.bit] {
    L "  BIT: $b  ([file size $b] 字节)"
}
# 时序
set rpt D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/impl_1/system_wrapper_timing_summary_routed.rpt
if {[file exists $rpt]} {
    set f [open $rpt r]; set t [read $f]; close $f
    foreach line [split $t "\n"] {
        if {[string match "*WNS*" $line] || [string match "*Timing constraints are not met*" $line]} {
            L "  时序: [string trim $line]"
        }
    }
}
L ""
L " 结束: [clock format [clock seconds]]"
close $LOG
exit 0
