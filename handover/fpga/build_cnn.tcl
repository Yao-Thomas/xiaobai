#=====================================================================
#  build_cnn.tcl —— CNN 集成后完整构建（综合 + 实现 + 出 bitstream）
#
#  前置: bd_cnn.tcl 已成功执行（BD 里已加 cnn_conv_pool_0 / cnn_fc_0 / cnn_mem_ic）
#  用法: vivado -mode batch -source build_cnn.tcl
#
#  注意: 完整构建 20~50 分钟，建议后台跑
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/build_cnn_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }
proc T {} { return [clock format [clock seconds] -format "%H:%M:%S"] }

L "======================================================"
L " CNN integration build"
L " start: [T]"
L "======================================================"

open_project $PROJ
L " project opened, Vivado [version -short]"
L " top: [get_property top [current_fileset]]"

# ---- 1. 刷新 IP 目录并重新生成 BD 输出 ----
L ""
L ">>> update_ip_catalog -rebuild [T]"
update_ip_catalog -rebuild
L ">>> generate_target all [T]"
if {[catch {generate_target all [get_files system.bd]} e1]} { L " WARN: $e1" } else { L " OK" }

# ---- 2. 现有 runs ----
L ""
L "=== existing runs ==="
foreach r [get_runs -quiet] {
    L "  [format %-16s $r] [get_property STATUS $r]  ([get_property PROGRESS $r])"
}

# ---- 3. 综合 ----
L ""
L ">>> synthesis [T]"
set sruns [get_runs -quiet *synth*]
if {[llength $sruns] == 0} {
    create_run -flow "Vivado Synthesis 2026" synth_1
    set sruns synth_1
}
set srun [lindex $sruns 0]
L " run: $srun"
reset_run $srun
launch_runs $srun -jobs 4
wait_on_run $srun
L " $srun: [get_property PROGRESS $srun]  [get_property STATUS $srun]"
if {![string match "*Complete*" [get_property STATUS $srun]]} {
    L " RESULT=SYNTH_FAIL"
    set rl [glob -nocomplain D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$srun/runme.log]
    foreach f $rl {
        set fp [open $f r]; set t [read $fp]; close $fp
        set k 0
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] && $k < 20} { L "   [string trim $line]"; incr k }
        }
    }
    close $LOG
    exit 1
}
L " synthesis OK [T]"

# ---- 4. 实现 + bitstream ----
L ""
L ">>> implementation + write_bitstream [T]"
set iruns [get_runs -quiet *impl*]
if {[llength $iruns] == 0} {
    create_run -flow "Vivado Implementation 2026" -parent $srun impl_1
    set iruns impl_1
}
set irun [lindex $iruns 0]
L " run: $irun"
reset_run $irun
launch_runs $irun -to_step write_bitstream -jobs 4
wait_on_run $irun
L " $irun: [get_property PROGRESS $irun]  [get_property STATUS $irun]"

# ---- 5. 时序 ----
L ""
L "=== timing summary ==="
set f "D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/system_wrapper_timing_summary_routed.rpt"
if {[file exists $f]} {
    set fp [open $f r]; set t [read $fp]; close $fp
    set k 0
    foreach line [split $t "\n"] {
        if {[string match "*WNS*" $line] || [string match "*WHS*" $line] ||
            [string match "*Timing constraints are not met*" $line] ||
            [string match "*All user specified timing constraints are met*" $line]} {
            if {$k < 10} { L "   [string trim $line]"; incr k }
        }
    }
} else { L "   (no timing_summary_routed.rpt)" }

# ---- 6. 资源利用率 ----
L ""
L "=== utilization ==="
set f2 "D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/system_wrapper_utilization_placed.rpt"
if {[file exists $f2]} {
    set fp [open $f2 r]; set t [read $fp]; close $fp
    foreach line [split $t "\n"] {
        foreach kk {"Slice LUTs" "Slice Registers" "Block RAM Tile" "DSPs" "Bonded IOB"} {
            if {[string match "| $kk*" $line]} { L "   [string trim $line]" }
        }
    }
} else { L "   (no utilization_placed.rpt)" }

# ---- 7. DRC ----
L ""
L "=== DRC ==="
set f3 "D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/system_wrapper_drc_routed.rpt"
if {[file exists $f3]} {
    set fp [open $f3 r]; set t [read $fp]; close $fp
    set k 0
    foreach line [split $t "\n"] {
        if {[string match "*Violations*" $line] || [string match "*Error*" $line]} {
            if {$k < 10} { L "   [string trim $line]"; incr k }
        }
    }
} else { L "   (no drc_routed.rpt)" }

# ---- 8. bitstream ----
L ""
L "=== bitstream ==="
set bits [glob -nocomplain D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/*.bit]
if {[llength $bits] > 0} {
    foreach b $bits { L " BITSTREAM: $b  ([file size $b] bytes)" }
    L " RESULT=OK"
} else {
    L " RESULT=IMPL_FAIL"
    set rl [glob -nocomplain D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/runme.log]
    foreach f $rl {
        set fp [open $f r]; set t [read $fp]; close $fp
        set k 0
        foreach line [split $t "\n"] {
            if {([string match "*ERROR*" $line] || [string match "*CRITICAL*" $line]) && $k < 20} {
                L "   [string trim $line]"; incr k
            }
        }
    }
}
L "=== end [T] ==="
close $LOG
exit 0
