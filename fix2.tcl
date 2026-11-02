#=====================================================================
#  fix2.tcl —— 更新工程内 ipshared 里的 GPU RTL, 强制重新生成, 重跑
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set BDIP {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/ip}
set SHARED {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/ipshared}
set SRC  {D:/ubuntu_iso/gpu_ip/src}
set LOG  [open "D:/ubuntu_iso/fix2_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 更新工程内 GPU RTL + 重跑 ==="
L " 当前时间: [clock format [clock seconds]]"

# ---- 1. 把新 RTL 覆盖到所有 ipshared 副本里 ----
set n 0
foreach d [glob -nocomplain $SHARED/*/src] {
    foreach f {gpu2d.v gpu2d_axi.v} {
        if {[file exists $SRC/$f]} {
            file copy -force $SRC/$f $d/$f
            incr n
            L " 覆盖: $d/$f"
        }
    }
}
L " 共覆盖 $n 个文件"

# 验证
foreach d [glob -nocomplain $SHARED/*/src] {
    if {[file exists $d/gpu2d_axi.v]} {
        set fp [open $d/gpu2d_axi.v r]; set t [read $fp]; close $fp
        set c [regexp -all {mst_err_pulse} $t]
        L " 检查 $d : mst_err_pulse 出现 $c 次"
    }
}

open_project $PROJ

# ---- 2. 删掉 gpu IP 的生成目录, 强制重生成 ----
foreach d [glob -nocomplain $BDIP/system_gpu_0_0*] {
    L " 删除生成缓存: [file tail $d]"
    file delete -force $d
}

open_bd_design [get_files system.bd]
set BDOBJ [get_files system.bd]
if {[catch {generate_target all $BDOBJ} e1]} { L " ⚠️ $e1" }
if {[catch {validate_bd_design} e2]} { L " ❌ BD 校验失败: $e2"; close $LOG; exit 1 }
save_bd_design
L " ✅ BD 校验+保存"

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]

# ---- 3. 重新综合 ----
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

set bits [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit]
if {[llength $bits] > 0} {
    foreach b $bits { L " ★★★ BITSTREAM: $b  ([file size $b] 字节)" }
    L " RESULT=OK"
} else {
    L " RESULT=IMPL_FAIL"
    set rl {D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/runme.log}
    if {[file exists $rl]} {
        set f [open $rl r]; set t [read $f]; close $f
        set k 0
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] && $k < 10} { L "   $line"; incr k }
        }
    }
}
L "=== 结束 ==="
close $LOG
exit 0
