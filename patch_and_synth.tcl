#=====================================================================
#  patch_and_synth.tcl —— 修补工程内 ipshared 的 GPU RTL, 只重跑综合+实现
#  不需要改系统时间 (HLS IP 已生成好并缓存)
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set BDROOT {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system}
set SRC  {D:/ubuntu_iso/gpu_ip/src}
set LOG  [open "D:/ubuntu_iso/patch_synth_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 修补 ipshared + 重跑综合实现 ==="
L " 当前时间: [clock format [clock seconds]]"

# ---- 1. 修补工程内所有 gpu RTL 副本 ----
set n 0
foreach d [glob -nocomplain $BDROOT/ipshared/*/src] {
    foreach f {gpu2d.v gpu2d_axi.v} {
        if {[file exists $SRC/$f]} {
            file copy -force $SRC/$f $d/$f
            incr n
        }
    }
}
L " 覆盖 $n 个文件"

# 也修 IP 生成目录里可能存在的副本
foreach d [glob -nocomplain $BDROOT/ip/system_gpu_0_0*] {
    foreach sub {src synth sim} {
        if {[file isdirectory $d/$sub]} {
            foreach f [glob -nocomplain $d/$sub/gpu2d*.v] {
                file copy -force $SRC/[file tail $f] $f
                incr n
            }
        }
    }
}
L " 共覆盖 $n 个文件"

# ---- 2. 验证 ----
set bad 0
foreach f [glob -nocomplain $BDROOT/ipshared/*/src/gpu2d_axi.v] {
    set fp [open $f r]; set t [read $fp]; close $fp
    set c [regexp -all {mst_err_pulse} $t]
    L "  [string range $f 60 end] : $c 处"
    if {$c == 0} { incr bad }
}
if {$bad > 0} { L " ❌ 还有 $bad 份是旧的"; }

# ---- 3. 重跑综合 ----
open_project $PROJ
set WFILE $BDROOT/hdl/system_wrapper.v
if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]

L ""
L ">>> 综合  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st"
if {![string match "*Complete*" $st]} {
    L " RESULT=SYNTH_FAIL"
    close $LOG
    exit 1
}
L " ✅ 综合通过"

# ---- 4. 实现 ----
L ""
L ">>> 实现  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]"

set rl {D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/runme.log}
set bits [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit]
if {[llength $bits] > 0} {
    foreach b $bits { L " ★★★ BITSTREAM: $b  ([file size $b] 字节)" }
    L " RESULT=OK"
} else {
    L " RESULT=IMPL_FAIL"
    if {[file exists $rl]} {
        set f [open $rl r]; set t [read $f]; close $f
        set k 0
        foreach line [split $t "\n"] {
            if {([string match "*ERROR*" $line] || [string match "*MDRV*" $line]) && $k < 12} {
                L "   $line"; incr k
            }
        }
    }
}
L "=== 结束 ==="
close $LOG
exit 0
