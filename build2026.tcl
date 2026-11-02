# build2026.tcl —— 用 Vivado 2026.1 出流 (不需要改系统时间!)
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/build2026_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }
proc T {} { return [clock format [clock seconds] -format "%H:%M:%S"] }

L "=== Vivado 2026.1 出流 ==="
L " 开始: [T]"
open_project $PROJ
L " ✅ 工程已打开"
L " Vivado: [version -short]"
L " 工程 top: [get_property top [current_fileset]]"

# ---- 1. 生成 BD 输出产品 ----
L ""
L ">>> 生成 BD 输出  [T]"
set bd [get_files system.bd]
if {[catch {generate_target all $bd} e1]} { L " ⚠️ generate_target: $e1" } else { L " ✅ BD 输出已生成" }

# ---- 2. 看有哪些 run ----
L ""
L "=== 现有 run ==="
foreach r [get_runs -quiet] {
    L "  [format %-16s %$r] [get_property STATUS $r]  ([get_property PROGRESS $r])"
}

# ---- 3. 综合 ----
L ""
L ">>> 综合  [T]"
set sruns [get_runs -quiet *synth*]
if {[llength $sruns] == 0} {
    L " 没有 synth run, 新建一个"
    create_run -flow "Vivado Synthesis 2026" synth_1
    set sruns synth_1
}
set srun [lindex $sruns 0]
L " 用 run: $srun"
reset_run $srun
launch_runs $srun -jobs 4
wait_on_run $srun
L " $srun: [get_property PROGRESS $srun]  [get_property STATUS $srun]"
if {![string match "*Complete*" [get_property STATUS $srun]]} {
    L " RESULT=SYNTH_FAIL"
    close $LOG
    exit 1
}
L " ✅ 综合通过  [T]"

# ---- 4. 实现 ----
L ""
L ">>> 实现 + 出流  [T]"
set iruns [get_runs -quiet *impl*]
if {[llength $iruns] == 0} {
    L " 没有 impl run, 新建"
    create_run -flow "Vivado Implementation 2026" -parent $srun impl_1
    set iruns impl_1
}
set irun [lindex $iruns 0]
L " 用 run: $irun"
reset_run $irun
launch_runs $irun -to_step write_bitstream -jobs 4
wait_on_run $irun
L " $irun: [get_property PROGRESS $irun]  [get_property STATUS $irun]"

# ---- 5. 结果 ----
L ""
set bits [glob -nocomplain D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/*/*.bit]
if {[llength $bits] > 0} {
    foreach b $bits { L " ★★★ BITSTREAM: $b  ([file size $b] 字节)" }
    L " RESULT=OK"
} else {
    L " RESULT=IMPL_FAIL"
    set rl [glob -nocomplain D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/*/runme.log]
    foreach f $rl {
        set fp [open $f r]; set t [read $fp]; close $fp
        set k 0
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] && $k < 12} { L "   [string trim $line]"; incr k }
        }
    }
}
L "=== 结束 [T] ==="
close $LOG
exit 0
