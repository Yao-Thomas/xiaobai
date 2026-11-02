set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG [open "D:/ubuntu_iso/bd_diag_cnn.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "==================== BD AXI topology ===================="
open_project $PROJ
open_bd_design [get_files system.bd]
L "BD opened"

L ""
L "--- hp3_merge ---"
set c [get_bd_cells hp3_merge]
foreach p [list CONFIG.NUM_SI CONFIG.NUM_MI CONFIG.NUM_SI {*}] {
  catch { L "  $p = [get_property $p $c]" }
}
L "  intf pins:"
foreach ip [lsort [get_bd_intf_pins -quiet hp3_merge/*]] { L "     $ip" }

L ""
L "--- ps7_0_axi_periph ---"
set c2 [get_bd_cells ps7_0_axi_periph]
catch { L "  NUM_MI = [get_property CONFIG.NUM_MI $c2]" }
catch { L "  NUM_SI = [get_property CONFIG.NUM_SI $c2]" }

L ""
L "--- S_AXI_HP* 的连接 ---"
foreach hp {S_AXI_HP0 S_AXI_HP1 S_AXI_HP2 S_AXI_HP3} {
  set net [get_bd_nets -quiet -of_objects [get_bd_intf_pins processing_system7_0/$hp]]
  L "  $hp  <- $net"
  foreach p [get_bd_intf_pins -quiet -of_objects $net] {
    if {[string match "*$hp*" $p]} { continue }
    L "         $p"
  }
}

L ""
L "--- gpu_0/m_axi 去哪了 ---"
set n [get_bd_nets -quiet -of_objects [get_bd_intf_pins gpu_0/m_axi]]
L "  gpu_0/m_axi net = $n"
foreach p [get_bd_intf_pins -quiet -of_objects $n] { L "     $p" }

L ""
L "--- 当前 IP repo 路径 ---"
L "  [get_property ip_repo_paths [current_project]]"

L ""
L "--- 现有 HLS/自研 IP 定义 ---"
foreach d [get_ipdefs -quiet *cnn*] { L "  cnn: $d" }
foreach d [get_ipdefs -quiet *scope*] { L "  scope: $d" }
foreach d [get_ipdefs -quiet *gpu*]  { L "  gpu: $d" }

close $LOG
puts "RESULT=OK"
exit 0