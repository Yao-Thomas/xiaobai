#=====================================================================
#  fix_master_seg.tcl —— 修正 GPU 主机口的地址范围 (64K -> 1G)
#  根因: 之前误把主机段设成 0x43CB0000/64K, 导致 GPU 写显存被互联丢弃
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG  [open "D:/ubuntu_iso/fix_master_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 修正 GPU 主机口地址段 ==="
open_project $PROJ
open_bd_design [get_files system.bd]

# 找到 GPU 主机口的段
set mseg ""
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*gpu_0/m_axi*" $s] || [string match "*gpu_0*HP3*" $s]} {
        L "  找到候选: $s"
        set mseg $s
    }
}
if {$mseg eq ""} {
    L " ❌ 找不到 gpu_0 的主机段, 列出所有含 gpu 的段:"
    foreach s [get_bd_addr_segs -quiet] {
        if {[string match "*gpu*" $s]} { L "    $s" }
    }
    close $LOG
    exit 1
}

L " 目标段: $mseg"
L " 修改前: offset=[get_property offset $mseg] range=[get_property range $mseg]"

set_property offset 0x00000000 $mseg
set_property range  1G         $mseg

L " 修改后: offset=[get_property offset $mseg] range=[get_property range $mseg]"

# 顺便确认从机段还是 0x43CB0000/64K
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*gpu_0/s_axi*" $s]} {
        L " 从机段 $s : offset=[get_property offset $s] range=[get_property range $s]"
    }
}

if {[catch {validate_bd_design} e]} { L " ❌ 校验失败: $e"; close $LOG; exit 1 }
save_bd_design
L " ✅ BD 校验+保存"

# ---- 重新综合 ----
set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
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
    L " RESULT=SYNTH_FAIL"; close $LOG; exit 1
}
L " ✅ 综合通过"

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
}
L "=== 结束 ==="
close $LOG
exit 0
