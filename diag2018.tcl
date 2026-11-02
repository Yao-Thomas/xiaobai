#=====================================================================
#  diag2018.tcl —— 列出 BD 里所有时钟/复位引脚及其连接, 找出没接的
#=====================================================================
set PROJ {D:/ubuntu_iso/tmp_try2018/gpu_proj}
open_project $PROJ/gpu_proj.xpr
open_bd_design [get_files system.bd]

set LOG [open "D:/ubuntu_iso/diag_result.txt" w]
puts $LOG "=== 所有未连接的时钟/复位引脚 ==="
foreach p [get_bd_pins -quiet -filter {TYPE==clk || TYPE==rst}] {
    set net [get_bd_nets -quiet -of_objects $p]
    if {$net eq ""} {
        puts $LOG "  ✗ $p   (TYPE=[get_property TYPE $p])"
    }
}
puts $LOG ""
puts $LOG "=== gpu_0 的所有引脚 ==="
foreach p [get_bd_pins -quiet gpu_0/*] {
    set net [get_bd_nets -quiet -of_objects $p]
    puts $LOG "  $p  ->  $net"
}
puts $LOG ""
puts $LOG "=== hp3_merge 的所有时钟/复位引脚 ==="
foreach p [get_bd_pins -quiet hp3_merge/*] {
    set t [get_property TYPE $p]
    if {$t eq "clk" || $t eq "rst"} {
        set net [get_bd_nets -quiet -of_objects $p]
        puts $LOG "  $p  ->  $net"
    }
}
puts $LOG ""
puts $LOG "=== audio 的时钟域 ==="
set anet [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins audio/M00_AXI]]
puts $LOG "  audio/M00_AXI net: $anet"
set apins [get_bd_intf_pins -quiet audio/M00_AXI]
foreach pp [get_bd_intf_pins -quiet audio/*] {
    set n [get_bd_nets -quiet -of_objects $pp]
    set t [get_property TYPE $pp]
    if {$t eq "clk" || $t eq "rst"} { puts $LOG "  audio pin $pp type=$t -> $n" }
}
puts $LOG ""
puts $LOG "=== 全 BD 的时钟源 ==="
foreach n [get_bd_nets -quiet -filter {TYPE==clk}] {
    set src [get_bd_pins -quiet -of_objects $n -filter {TYPE==clk}]
    puts $LOG "  $n"
}
close $LOG
puts ">>> 诊断完成"
exit 0
