#=====================================================================
#  check_addr.tcl —— 查 GPU 主机口的地址映射是否正确
#=====================================================================
open_project {D:/ubuntu_iso/atk2018/atk2018.xpr}
open_bd_design [get_files system.bd]

set LOG [open "D:/ubuntu_iso/check_addr_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 1. GPU 主机口连到哪 ==="
set gnet [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins gpu_0/M_AXI]]
L "  gpu_0/M_AXI net: $gnet"
foreach p [get_bd_intf_pins -quiet -of_objects $gnet] {
    L "    -> $p  (mode=[get_property MODE $p])"
}
L ""
L "=== 2. hp3_merge 的连接 ==="
foreach p [get_bd_intf_pins -quiet hp3_merge/*] {
    set n [get_bd_intf_nets -quiet -of_objects $p]
    L "  $p (mode=[get_property MODE $p]) -> $n"
}
L ""
L "=== 3. 所有主机的地址段 (关键!) ==="
foreach s [lsort [get_bd_addr_segs]] {
    set o [get_property offset $s]
    set r [get_property range $s]
    set m [get_property MASTER_ADDR_SPACE $s 2>/dev/null]
    if {[string match "*gpu*" $s] || [string match "*hp3*" $s] || [string match "*HP3*" $s]} {
        L "  ★ [format %-58s $s] off=$o range=$r"
    }
}
L ""
L "=== 4. gpu_0 的主机地址空间 ==="
foreach as [get_bd_addr_spaces -quiet -of_objects [get_bd_cells gpu_0]] {
    L "  地址空间: $as"
    foreach s [get_bd_addr_segs -quiet -of_objects $as] {
        L "    段: $s  off=[get_property offset $s] range=[get_property range $s]"
    }
}
L ""
L "=== 5. 从机地址 (gpu 控制寄存器) ==="
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_cells gpu_0]] {
    L "  $s"
}
close $LOG
puts ">>> 完成"
exit 0
