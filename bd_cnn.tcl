#=====================================================================
#  bd_cnn.tcl —— 把 CNN 两个 HLS IP 集成进主工程 block design
#
#  设计:
#    cnn_conv_pool_0 (xilinx.com:hls:cnn_conv_pool_q:1.0)
#    cnn_fc_0        (xilinx.com:hls:cnn_fc_q:1.0)
#
#    AXI-Lite 控制:
#      ps7_0_axi_periph NUM_MI 18 -> 20
#      M18 -> cnn_conv_pool_0/s_axi_control   @ 0x43CD0000 / 64K
#      M19 -> cnn_fc_0/s_axi_control          @ 0x43CE0000 / 64K
#
#    数据通路 (m_axi -> DDR):
#      新建 cnn_mem_ic (NUM_SI=6, NUM_MI=1)
#        S00 <- cnn_conv_pool_0/m_axi_gmem_img
#        S01 <- cnn_conv_pool_0/m_axi_gmem_w
#        S02 <- cnn_conv_pool_0/m_axi_gmem_out
#        S03 <- cnn_fc_0/m_axi_gmem_x
#        S04 <- cnn_fc_0/m_axi_gmem_w
#        S05 <- cnn_fc_0/m_axi_gmem_out
#      cnn_mem_ic/M00 -> hp3_merge/S02_AXI
#      hp3_merge NUM_SI 2 -> 3
#
#    中断: 两个 interrupt 收进 xlconcat_0 (NUM_PORTS +2)
#
#  用法: vivado -mode batch -source bd_cnn.tcl
#  安全: 任何一步出错就 exit 1，不保存 BD
#=====================================================================

set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/bd_cnn_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }
proc FAIL {msg} { global LOG; L "!! FAIL: $msg"; close $LOG; puts "RESULT=FAIL"; exit 1 }

L "======================================================"
L " BD CNN integration"
L " time: [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ
L "project opened"

# ---------------- 0. 前置检查 ----------------
L ""
L ">>> 0. pre-checks"
foreach vlnv {xilinx.com:hls:cnn_conv_pool_q:1.0 xilinx.com:hls:cnn_fc_q:1.0} {
    if {[llength [get_ipdefs -quiet $vlnv]] == 0} { FAIL "IP def not found: $vlnv" }
    L "  OK ipdef: $vlnv"
}

open_bd_design [get_files system.bd]
L "  BD opened"

# 记录原始状态，便于回滚判断
set orig_num_mi [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
set orig_hp3_si [get_property CONFIG.NUM_SI [get_bd_cells hp3_merge]]
L "  before: ps7_0_axi_periph NUM_MI=$orig_num_mi , hp3_merge NUM_SI=$orig_hp3_si"

# ---------------- 1. 清理旧实例（支持重跑） ----------------
L ""
L ">>> 1. cleanup old instances"
foreach c {cnn_conv_pool_0 cnn_fc_0 cnn_mem_ic} {
    if {[llength [get_bd_cells -quiet $c]] > 0} {
        catch { delete_bd_objs [get_bd_cells $c] }
        L "  removed $c"
    }
}

# ---------------- 2. 建两个 CNN cell ----------------
L ""
L ">>> 2. create CNN cells"
if {[catch {create_bd_cell -type ip -vlnv xilinx.com:hls:cnn_conv_pool_q:1.0 cnn_conv_pool_0} e]} {
    FAIL "create cnn_conv_pool_0: $e"
}
L "  cnn_conv_pool_0 created"
if {[catch {create_bd_cell -type ip -vlnv xilinx.com:hls:cnn_fc_q:1.0 cnn_fc_0} e]} {
    FAIL "create cnn_fc_0: $e"
}
L "  cnn_fc_0 created"

foreach c {cnn_conv_pool_0 cnn_fc_0} {
    L "  --- $c pins ---"
    foreach p [lsort [get_bd_intf_pins -quiet $c/*]] { L "      iface $p" }
    foreach p [lsort [get_bd_pins -quiet $c/*]] {
        if {[string match "*clk*" $p] || [string match "*rst*" $p] || [string match "*interrupt*" $p]} {
            L "      pin   $p"
        }
    }
}

# ---------------- 3. 建 CNN 内存 AXI 互联 ----------------
L ""
L ">>> 3. create cnn_mem_ic (NUM_SI=6, NUM_MI=1)"
if {[catch {
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 cnn_mem_ic
} e]} { FAIL "create cnn_mem_ic: $e" }
set_property -dict [list CONFIG.NUM_SI {6} CONFIG.NUM_MI {1}] [get_bd_cells cnn_mem_ic]
L "  cnn_mem_ic created"

# ---------------- 4. 连 m_axi ----------------
L ""
L ">>> 4. connect m_axi bundles"
set pairs [list \
    [list cnn_conv_pool_0/m_axi_gmem_img cnn_mem_ic/S00_AXI] \
    [list cnn_conv_pool_0/m_axi_gmem_w   cnn_mem_ic/S01_AXI] \
    [list cnn_conv_pool_0/m_axi_gmem_out cnn_mem_ic/S02_AXI] \
    [list cnn_fc_0/m_axi_gmem_x          cnn_mem_ic/S03_AXI] \
    [list cnn_fc_0/m_axi_gmem_w          cnn_mem_ic/S04_AXI] \
    [list cnn_fc_0/m_axi_gmem_out        cnn_mem_ic/S05_AXI] ]
foreach pr $pairs {
    set a [lindex $pr 0]; set b [lindex $pr 1]
    if {[catch {connect_bd_intf_net [get_bd_intf_pins $a] [get_bd_intf_pins $b]} e]} {
        FAIL "connect $a <-> $b : $e"
    }
    L "  $a  <->  $b"
}

# ---------------- 5. cnn_mem_ic/M00 -> hp3_merge/S02 ----------------
L ""
L ">>> 5. hp3_merge NUM_SI $orig_hp3_si -> 3; connect cnn_mem_ic/M00"
set_property -dict [list CONFIG.NUM_SI {3}] [get_bd_cells hp3_merge]
L "  hp3_merge NUM_SI = [get_property CONFIG.NUM_SI [get_bd_cells hp3_merge]]"
L "  hp3_merge pins now:"
foreach ip [lsort [get_bd_intf_pins -quiet hp3_merge/*]] { L "     $ip" }
if {[llength [get_bd_intf_pins -quiet hp3_merge/S02_AXI]] == 0} {
    FAIL "hp3_merge/S02_AXI not present after NUM_SI=3"
}
if {[catch {
    connect_bd_intf_net [get_bd_intf_pins cnn_mem_ic/M00_AXI] [get_bd_intf_pins hp3_merge/S02_AXI]
} e]} { FAIL "connect cnn_mem_ic/M00 -> hp3_merge/S02: $e" }
L "  cnn_mem_ic/M00_AXI <-> hp3_merge/S02_AXI"

# ---------------- 6. AXI-Lite 控制 ----------------
L ""
L ">>> 6. AXI-Lite control: NUM_MI $orig_num_mi -> 20"
set_property -dict [list CONFIG.NUM_MI {20}] [get_bd_cells ps7_0_axi_periph]
L "  NUM_MI = [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]"

foreach pr [list [list ps7_0_axi_periph/M18_AXI cnn_conv_pool_0/s_axi_control] \
                 [list ps7_0_axi_periph/M19_AXI cnn_fc_0/s_axi_control]] {
    set a [lindex $pr 0]; set b [lindex $pr 1]
    if {[catch {connect_bd_intf_net [get_bd_intf_pins $a] [get_bd_intf_pins $b]} e]} {
        FAIL "connect $a <-> $b : $e"
    }
    L "  $a  <->  $b"
}

# ---------------- 7. 时钟 / 复位 ----------------
L ""
L ">>> 7. clocks and resets"
set CLK [get_bd_pins processing_system7_0/FCLK_CLK0]
set RST [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]
L "  CLK = $CLK"
L "  RST = $RST"

# 7a. CNN 本身的 clk/rst
foreach c {cnn_conv_pool_0 cnn_fc_0} {
    catch { connect_bd_net $CLK [get_bd_pins $c/ap_clk] }
    catch { connect_bd_net $RST [get_bd_pins $c/ap_rst_n] }
}
L "  cnn ap_clk/ap_rst_n connected"

# 7b. cnn_mem_ic 的时钟复位（ACLK/ARESETN + M00_ACLK/M00_ARESETN + S0x_ACLK/S0x_ARESETN）
foreach pn [get_bd_pins -quiet cnn_mem_ic/*] {
    set pname [string range $pn [expr {[string last "/" $pn]+1}] end]
    if {[string match "*ACLK*" $pname]} {
        catch { connect_bd_net $CLK [get_bd_pins $pn] }
    } elseif {[string match "*ARESETN*" $pname]} {
        catch { connect_bd_net $RST [get_bd_pins $pn] }
    }
}
L "  cnn_mem_ic clocks/resets connected"

# 7c. ps7_0_axi_periph 的 M18/M19 时钟复位
foreach pn {M18_ACLK M18_ARESETN M19_ACLK M19_ARESETN} {
    catch { connect_bd_net $CLK [get_bd_pins ps7_0_axi_periph/$pn] }
    catch { connect_bd_net $RST [get_bd_pins ps7_0_axi_periph/$pn] }
}
L "  ps7_0_axi_periph M18/M19 clk/rst connected"

# 7d. hp3_merge 的 S02 时钟复位
foreach pn {S02_ACLK S02_ARESETN} {
    catch { connect_bd_net $CLK [get_bd_pins hp3_merge/$pn] }
    catch { connect_bd_net $RST [get_bd_pins hp3_merge/$pn] }
}
L "  hp3_merge S02 clk/rst connected"

# ---------------- 8. 中断 ----------------
L ""
L ">>> 8. interrupts"
if {[llength [get_bd_cells -quiet xlconcat_0]] > 0} {
    set np [get_property CONFIG.NUM_PORTS [get_bd_cells xlconcat_0]]
    L "  xlconcat_0 NUM_PORTS = $np"
    if {[catch { set_property -dict [list CONFIG.NUM_PORTS [expr {$np+2}]] [get_bd_cells xlconcat_0] } e]} {
        L "  !! cannot grow xlconcat_0: $e (interrupts left unconnected)"
    } else {
        L "  xlconcat_0 NUM_PORTS -> [expr {$np+2}]"
        catch { connect_bd_net [get_bd_pins cnn_conv_pool_0/interrupt] [get_bd_pins xlconcat_0/In$np] }
        catch { connect_bd_net [get_bd_pins cnn_fc_0/interrupt]        [get_bd_pins xlconcat_0/In[expr {$np+1}]] }
        L "  interrupts -> xlconcat_0/In$np , In[expr {$np+1}]"
    }
} else {
    L "  no xlconcat_0 found; interrupts will be left unconnected (warning only)"
}

# ---------------- 9. 地址 ----------------
L ""
L ">>> 9. assign addresses"
set addr_list [list \
    [list cnn_conv_pool_0 0x43CD0000] \
    [list cnn_fc_0        0x43CE0000] ]
foreach al $addr_list {
    set cell [lindex $al 0]; set off [lindex $al 1]
    set sseg ""
    foreach s [get_bd_addr_segs -quiet] {
        if {[string match "*$cell/s_axi_control*" $s]} { set sseg $s }
    }
    if {$sseg eq ""} { FAIL "addr seg not found for $cell" }
    if {[catch {
        assign_bd_address -force -offset $off -range 64K \
            -target_address_space /processing_system7_0/Data $sseg
    } e]} { FAIL "assign $cell -> $off : $e" }
    L "  $sseg -> $off / 64K"
}

# ---------------- 10. 校验 / 保存 / 生成 ----------------
L ""
L ">>> 10. validate"
if {[catch {validate_bd_design} e]} {
    L "  !! validate_bd_design FAILED: $e"
    FAIL "BD validation failed (BD NOT saved)"
}
L "  BD validated OK"

save_bd_design
L "  BD saved"

if {[catch {generate_target all [get_files system.bd]} e]} {
    FAIL "generate_target: $e"
}
L "  targets generated"

# ---------------- 11. 汇总 ----------------
L ""
L ">>> 11. summary"
L "  ps7_0_axi_periph NUM_MI = [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]"
L "  hp3_merge        NUM_SI = [get_property CONFIG.NUM_SI [get_bd_cells hp3_merge]]"
L "  cnn_mem_ic       NUM_SI = [get_property CONFIG.NUM_SI [get_bd_cells cnn_mem_ic]]"
L ""
L "  new address segments:"
foreach s [lsort [get_bd_addr_segs -quiet]] {
    set o "?"
    catch { set o [get_property offset $s] }
    if {$o eq "0x43CD0000" || $o eq "0x43CE0000"} {
        set r "?"; catch { set r [get_property range $s] }
        L "    $s = $o / $r"
    }
}

close $LOG
puts "RESULT=OK"
exit 0
