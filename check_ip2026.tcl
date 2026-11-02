# check_ip2026.tcl —— 检查 2026.1 里有没有正点原子工程用到的关键 IP
puts "=========================================="
puts " Vivado [version -short]  IP 可用性检查"
puts "=========================================="
foreach pat {v_tc v_frmbuf v_axi4s_vid_out v_vid_in_axi4s axi_vdma v_tpg xlconstant axi_gpio axi_iic} {
    set r [get_ipdefs -quiet *${pat}*]
    puts "  ${pat}:"
    if {[llength $r] == 0} {
        puts "     (none)"
    } else {
        foreach x [lrange $r 0 4] { puts "     $x" }
    }
}
puts "=========================================="
puts "IPCHECK-DONE"
exit 0
