set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/addrspaces.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

open_project $PROJ
open_bd_design [get_files system.bd]

L "=========== 所有地址空间 ==========="
foreach s [lsort [get_bd_addr_spaces -quiet]] { L "  $s" }

L ""
L "=========== CNN 那两个 cell 的所有接口引脚 ==========="
foreach c {cnn_conv_pool_0 cnn_fc_0 cnn_mem_ic} {
    L "  --- $c ---"
    foreach p [lsort [get_bd_intf_pins -quiet $c/*]] {
        set m ""; catch { set m [get_property MODE $p] }
        L "     [format %-46s %s] mode=%s" $p "" $m
    }
}

L ""
L "=========== 每个 CNN 主控接口关联的地址空间 ==========="
foreach ip {cnn_conv_pool_0/m_axi_gmem_img cnn_conv_pool_0/m_axi_gmem_w cnn_conv_pool_0/m_axi_gmem_out cnn_fc_0/m_axi_gmem_x cnn_fc_0/m_axi_gmem_w cnn_fc_0/m_axi_gmem_out cnn_mem_ic/M00_AXI} {
    set spc ""
    catch { set spc [get_bd_addr_spaces -quiet -of_objects [get_bd_intf_pins -quiet $ip]] }
    L "  [format %-38s %s]" $ip "space=($spc)"
}

L ""
L "=========== HP3 上的地址段 ==========="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    if {[string match "*HP3*" $s] || [string match "*DDR_LOWOCM*" $s]} {
        set o "?"; catch { set o [get_property offset $s] }
        set r "?"; catch { set r [get_property range $s] }
        L "  $s = $o / $r"
    }
}

close $LOG
puts "RESULT=OK"
exit 0