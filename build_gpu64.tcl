#=====================================================================
#  build_gpu64.tcl -- synthesize / implement / write bitstream for the
#                    64-bit GPU (8 bytes per AXI beat) design
#  usage: vivado -mode batch -source build_gpu64.tcl
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/build_gpu64_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }
proc T {} { return [clock format [clock seconds] -format "%H:%M:%S"] }

L "======================================================"
L " 64-bit GPU build"
L " start: [T]"
L "======================================================"

open_project $PROJ
L " project opened, Vivado [version -short]"
L " top: [get_property top [current_fileset]]"

# ---- 1. regenerate BD outputs ----
L ""
L ">>> generate_target all [T]"
if {[catch {generate_target all [get_files system.bd]} e1]} { L " WARN: $e1" } else { L " OK" }

# ---- 2. runs ----
L ""
L "=== existing runs ==="
foreach r [get_runs -quiet] {
    L "  [format %-16s $r] [get_property STATUS $r]  ([get_property PROGRESS $r])"
}

# ---- 3. synthesis ----
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
            if {[string match "*ERROR*" $line] && $k < 15} { L "   [string trim $line]"; incr k }
        }
    }
    close $LOG
    exit 1
}
L " synthesis OK [T]"

# ---- 4. implementation + bitstream ----
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

# ---- 5. timing / utilization ----
L ""
L "=== timing summary ==="
foreach rpt {timing_summary_routed.rpt} {
    set f "D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/$rpt"
    if {[file exists $f]} {
        set fp [open $f r]; set t [read $fp]; close $fp
        set k 0
        foreach line [split $t "\n"] {
            if {[string match "*WNS*" $line] || [string match "*WHS*" $line] ||
                [string match "*Timing constraints are not met*" $line] ||
                [string match "*All user specified timing constraints are met*" $line]} {
                if {$k < 8} { L "   [string trim $line]"; incr k }
            }
        }
    } else { L "   (no $rpt)" }
}

# ---- 6. bitstream ----
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
            if {([string match "*ERROR*" $line] || [string match "*CRITICAL*" $line]) && $k < 15} {
                L "   [string trim $line]"; incr k
            }
        }
    }
}
L "=== end [T] ==="
close $LOG
exit 0
