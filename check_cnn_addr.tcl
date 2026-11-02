#=====================================================================
#  check_cnn_addr.tcl —— 检查 CNN 主控的地址分配
#
#  背景：CNN 的 m_axi 主控（6 条）要能访问 DDR，必须在 BD 里
#        给它们分配地址段（address segment）。如果只给从设备
#        （s_axi_control）分了地址，主控就是"能收命令但搬不了数据"，
#        表现正是"IP 跑完但输出缓冲没变"。
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/cnn_addr_check.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

open_project $PROJ
open_bd_design [get_files system.bd]
L "BD opened"

L ""
L "=========== 1) 所有主控接口 ==========="
foreach c [get_bd_cells -quiet] {
    foreach ip [get_bd_intf_pins -quiet $c/*] {
        set m ""
        catch { set m [get_property MODE $ip] }
        if {$m eq "Master"} { L "   MASTER  $ip" }
    }
}

L ""
L "=========== 2) CNN 相关的地址段 ==========="
foreach m {cnn_conv_pool_0/m_axi_gmem_img cnn_conv_pool_0/m_axi_gmem_w \
           cnn_conv_pool_0/m_axi_gmem_out cnn_fc_0/m_axi_gmem_x \
           cnn_fc_0/m_axi_gmem_w cnn_fc_0/m_axi_gmem_out cnn_mem_ic/M00_AXI} {
    if {[llength [get_bd_intf_pins -quiet $m]] == 0} {
        L "   !! 找不到 $m"
        continue
    }
    L ""
    L "   --- $m ---"
    set segs [get_bd_addr_segs -quiet -of_objects [get_bd_intf_pins $m]]
    if {[llength $segs] == 0} {
        L "      ★ 没有分配任何地址段！"
    } else {
        foreach s $segs {
            set o "?"; set r "?"
            catch { set o [get_property offset $s] }
            catch { set r [get_property range $s] }
            L "      $s = $o / $r"
        }
    }
}

L ""
L "=========== 3) hp3_merge 的连接 ==========="
foreach ip [lsort [get_bd_intf_pins -quiet hp3_merge/*]] {
    set net ""
    catch { set net [get_bd_intf_nets -quiet -of_objects $ip] }
    L "   $ip  ->  $net"
}

L ""
L "=========== 4) HP3 上挂了谁 ==========="
set hp3 [get_bd_intf_pins -quiet processing_system7_0/S_AXI_HP3]
L "   S_AXI_HP3 接口: $hp3"
foreach n [get_bd_intf_nets -quiet -of_objects $hp3] {
    L "   net = $n"
    foreach p [get_bd_intf_pins -quiet -of_objects $n] { L "      $p" }
}

L ""
L "=========== 5) 所有主控的地址空间（Data）映射 ==========="
set spc [get_bd_addr_spaces -quiet]
foreach s [lsort $spc] {
    set segs [get_bd_addr_segs -quiet -of_objects $s]
    if {[llength $segs] == 0} { continue }
    L "   [format %-52s $s] 有 [llength $segs] 个段"
}

close $LOG
puts "RESULT=OK"
exit 0
