#=====================================================================
#  ipstatus.tcl —— 查哪些 IP 生成失败
#=====================================================================
open_project {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG [open "D:/ubuntu_iso/ipstatus_result.txt" w]
puts $LOG "=== 工程里的 IP ==="
set bad 0
foreach ip [get_ips] {
    set nm [get_property NAME $ip]
    set st "?"
    catch {set st [get_property STATUS $ip]}
    set pr "?"
    catch {set pr [get_property PROGRESS $ip]}
    if {![string match "*Complete*" $st]} { incr bad }
    puts $LOG "  [format %-42s $nm] $pr  $st"
}
puts $LOG ""
puts $LOG "未完成的 IP 数: $bad"
puts $LOG ""
puts $LOG "=== v_frmbuf 相关的 ==="
foreach ip [get_ips *frmbuf*] {
    puts $LOG "  [get_property NAME $ip]  [get_property VLNV $ip]  [get_property STATUS $ip]"
}
puts $LOG ""
puts $LOG "=== v_frmbuf_wr 的生成产物 ==="
set d {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/ip/system_v_frmbuf_wr_0_0}
if {[file exists $d]} {
    foreach f [glob -nocomplain $d/*] { puts $LOG "  [file tail $f]" }
    set sd $d/synth
    if {[file exists $sd]} {
        puts $LOG "  synth/:"
        foreach f [glob -nocomplain $sd/*] { puts $LOG "    [file tail $f]" }
    }
} else {
    puts $LOG "  目录不存在!"
}
close $LOG
puts ">>> 完成"
exit 0
