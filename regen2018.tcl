#=====================================================================
#  regen2018.tcl —— 强制重新生成 BD 的 IP 输出, 然后出 bitstream
#  原因: 把 IP 版本 2.2->2.1 / 6.2->6.1 后, 旧的生成缓存没更新
#=====================================================================
set LOG [open "D:/ubuntu_iso/regen_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 重新生成 IP + 出 bitstream"
L " 开始: [clock format [clock seconds]]"
L "======================================================"

open_project {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.xpr}
open_bd_design [get_files system.bd]

# ---- 删掉旧的 IP 生成缓存, 强制重来 ----
set ipdir {D:/ubuntu_iso/tmp_try2018/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/ip}
set synthdir {D:/ubuntu_iso/tmp_try2018/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/synth}
set hdir {D:/ubuntu_iso/tmp_try2018/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/hdl}
foreach d [list $ipdir $synthdir] {
    if {[file exists $d]} {
        L " 删除旧缓存: $d"
        file delete -force $d
    }
}
# hdl 里保留 wrapper, 删掉其它
foreach f [glob -nocomplain $hdir/*] {
    if {![string match "*wrapper*" [file tail $f]]} {
        L " 删除: [file tail $f]"
        file delete -force $f
    }
}

# ---- 重新生成 ----
L ""
L ">>> reset_target + generate_target (可能 10-20 分钟)  [clock format [clock seconds]]"
if {[catch {
    reset_target all [get_files system.bd]
    generate_target all [get_files system.bd]
} gerr]} {
    L " ⚠️ generate_target: $gerr"
}
L " ✅ 生成完成  [clock format [clock seconds]]"

# ---- wrapper ----
set WFILE $hdir/system_wrapper.v
if {![file exists $WFILE]} {
    catch {make_wrapper -files [get_files system.bd] -top}
}
if {[file exists $WFILE]} {
    if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
    L " wrapper: $WFILE"
}
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " top = [get_property top [current_fileset]]"

# ---- 综合 ----
L ""
L ">>> 综合 synth_1  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st  [clock format [clock seconds]]"

if {![string match "*Complete*" $st]} {
    L " ❌ 综合还是失败, 日志末尾:"
    set rl {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/synth_1/runme.log}
    if {[file exists $rl]} {
        set f [open $rl r]; set t [read $f]; close $f
        set lines [split $t "\n"]
        foreach line [lrange $lines end-20 end] { L "   $line" }
    }
    close $LOG
    exit 1
}

# ---- 实现 ----
L ""
L ">>> 实现 impl_1  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]  [clock format [clock seconds]]"

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/impl_1/*.bit] {
    L "  BIT: $b  ([file size $b] 字节)"
}
L " 结束: [clock format [clock seconds]]"
close $LOG
exit 0
