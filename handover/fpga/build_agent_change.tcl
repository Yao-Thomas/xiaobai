#=====================================================================
#  build_agent_change.tcl —— 出流（agent 改过 HDL 的版本）
#
#  ★ 和 build_cnn.tcl 的区别：
#    build_cnn.tcl 会先跑 update_ip_catalog -rebuild + generate_target all。
#    这两个命令会【重新从 IP 仓库复制源码到 .gen/ipshared】，
#    ⇒ 把 agent 直接改在 ipshared 里的 HDL 覆盖掉，改动就白改了。
#
#    所以这个脚本【跳过】那两步，直接 reset_run + 综合 + 实现 + 出流。
#    ——ipshared 里的源码就是综合的最终输入，改它一定生效。
#
#  ★ 什么时候用哪个：
#    · 改的是 IP 仓库源码（gpu_ip/src/…）且重新打包了 IP  → 用 build_cnn.tcl
#    · 改的是工程 .gen/ipshared 里的源码（agent 快速改硬件）→ 用这个
#=====================================================================

set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/build_agent_change_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }
proc T {} { return [clock format [clock seconds] -format "%H:%M:%S"] }

L "======================================================"
L " agent 改动后出流（跳过 IP 重新生成）"
L " start: [T]"
L "======================================================"

open_project $PROJ
L " project opened, Vivado [version -short]"

# ★★★ 这里【故意不做】update_ip_catalog / generate_target ——
#     它们会覆盖 agent 改在 ipshared 里的源码
L ""
L ">>> 跳过 update_ip_catalog / generate_target（保留 ipshared 里的改动）"

# ---- 顺便把 agent 改的那行打印出来，作为证据 ----
set gp {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.gen/sources_1/bd/system/ipshared/eaea/src/gpu2d_axi.v}
if {[file exists $gp]} {
    set fp [open $gp r]; set t [read $fp]; close $fp
    foreach line [split $t "\n"] {
        if {[string match "*default: s_axi_rdata*" $line]} {
            L " ★ 当前 gpu2d_axi.v 的 default 分支: [string trim $line]"
        }
    }
} else {
    L " !! 找不到 $gp"
}

# ---- 综合 ----
L ""
L ">>> synthesis [T]"
set srun [lindex [get_runs -quiet *synth*] 0]
if {$srun eq ""} { set srun synth_1 }
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

# ---- 实现 + 出流 ----
L ""
L ">>> implementation + write_bitstream [T]"
set irun [lindex [get_runs -quiet *impl*] 0]
if {$irun eq ""} { set irun impl_1 }
reset_run $irun
launch_runs $irun -to_step write_bitstream -jobs 4
wait_on_run $irun
L " $irun: [get_property PROGRESS $irun]  [get_property STATUS $irun]"

# ---- 时序 ----
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
}

# ---- bitstream ----
L ""
L "=== bitstream ==="
set bits [glob -nocomplain D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/$irun/*.bit]
if {[llength $bits] > 0} {
    foreach b $bits { L " BITSTREAM: $b  ([file size $b] bytes)" }
    L " RESULT=OK"
} else {
    L " RESULT=IMPL_FAIL"
}
L "=== end [T] ==="
close $LOG
exit 0
