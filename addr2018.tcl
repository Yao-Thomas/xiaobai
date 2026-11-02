#=====================================================================
#  addr2018.tcl —— 给 GPU 分配地址 0x43CB0000
#=====================================================================
open_project {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.xpr}
open_bd_design [get_files system.bd]

set LOG [open "D:/ubuntu_iso/addr_result.txt" w]
puts $LOG "=== gpu_0 的地址段 (所有候选) ==="
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_cells gpu_0]] {
    puts $LOG "  $s"
}
puts $LOG ""
puts $LOG "=== gpu_0 的从接口 ==="
foreach i [get_bd_intf_pins -quiet -of_objects [get_bd_cells gpu_0]] {
    puts $LOG "  $i  (MODE=[get_property MODE $i])"
}

# 用真实名字设置地址
assign_bd_address -quiet
set segs [get_bd_addr_segs -quiet -of_objects [get_bd_cells gpu_0]]
if {[llength $segs] > 0} {
    set seg [lindex $segs 0]
    set_property offset 0x43CB0000 $seg
    set_property range  64K        $seg
    puts $LOG ""
    puts $LOG " ✅ 已设置: $seg"
    puts $LOG "    offset = [get_property offset $seg]"
    puts $LOG "    range  = [get_property range $seg]"
} else {
    puts $LOG ""
    puts $LOG " ❌ 还是找不到地址段"
}

# 打印完整地址映射
puts $LOG ""
puts $LOG "=== 完整地址映射 ==="
foreach s [get_bd_addr_segs] {
    set off [get_property offset $s]
    set rg  [get_property range $s]
    puts $LOG "  [format %-52s $s] $off / $rg"
}

validate_bd_design
save_bd_design
puts $LOG ""
puts $LOG "✅ 已保存"

# 确认
set seg2 [get_bd_addr_segs -quiet -of_objects [get_bd_cells gpu_0]]
if {[llength $seg2] > 0} {
    puts $LOG "GPU 最终地址: [get_property offset [lindex $seg2 0]]"
}
close $LOG
puts ">>> 地址分配完成"
exit 0
