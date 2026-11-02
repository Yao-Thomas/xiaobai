#=====================================================================
#  bd_gpu64.tcl -- install the 64-bit GPU IP into the block design
#  (BD only, no synthesis)
#
#  m_axi went from 32-bit to 64-bit, so the port list changed: gpu_0 must
#  be deleted and re-created.  The interconnect then drops the auto_us
#  upsizer on that path because SI and MI are both 64-bit now.
#
#  usage: vivado -mode batch -source bd_gpu64.tcl
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/bd_gpu64_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " install 64-bit GPU IP into BD"
L " time: [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ
L " project opened, Vivado [version -short]"

# ---- 1. refresh IP catalog ----
L ""
L ">>> update_ip_catalog -rebuild"
update_ip_catalog -rebuild
foreach d [get_ipdefs -quiet *gpu2d*] { L "   found IP: $d" }

# ---- 2. open BD ----
open_bd_design [get_files system.bd]
L " BD opened"

# ---- 3. remove old gpu_0 and hp3_merge ----
L ""
L ">>> remove old gpu_0 / hp3_merge"
if {[llength [get_bd_cells -quiet hp3_merge]] > 0} {
    catch {delete_bd_objs [get_bd_cells hp3_merge]}
    L "   deleted hp3_merge"
}
if {[llength [get_bd_cells -quiet gpu_0]] > 0} {
    catch {delete_bd_objs [get_bd_cells gpu_0]}
    L "   deleted gpu_0"
}
set oldnet [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins processing_system7_0/S_AXI_HP3]]
foreach n $oldnet {
    catch {delete_bd_objs $n}
    L "   removed net on HP3: $n"
}

# ---- 4. re-create gpu_0 (64-bit) ----
L ""
L ">>> create gpu_0"
if {[catch {create_bd_cell -type ip -vlnv dsh:user:gpu2d_axi:1.0 gpu_0} e1]} {
    L " !! create gpu_0 failed: $e1"
    close $LOG
    exit 1
}
L "   gpu_0 created"
L "   gpu_0 intf pins:"
foreach p [lsort [get_bd_intf_pins -quiet gpu_0/*]] { L "      $p" }

# ---- 5. create hp3_merge and wire it ----
L ""
L ">>> create hp3_merge (2 SI / 1 MI) and wire"
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 hp3_merge
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells hp3_merge]

connect_bd_intf_net [get_bd_intf_pins audio/M00_AXI]     [get_bd_intf_pins hp3_merge/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins gpu_0/m_axi]       [get_bd_intf_pins hp3_merge/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins hp3_merge/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP3]
L "   audio -> hp3_merge/S00, gpu_0/m_axi -> hp3_merge/S01, M00 -> PS HP3"

set_property -dict [list CONFIG.NUM_MI {17}] [get_bd_cells ps7_0_axi_periph]
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M16_AXI] [get_bd_intf_pins gpu_0/s_axi]
L "   ps7_0_axi_periph/M16 -> gpu_0/s_axi"

# ---- 6. clocks / resets ----
L ""
L ">>> connect clocks / resets"
set CLK [get_bd_pins processing_system7_0/FCLK_CLK0]
set RST [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]
catch {connect_bd_net $CLK [get_bd_pins gpu_0/aclk]}
catch {connect_bd_net $RST [get_bd_pins gpu_0/aresetn]}
foreach p {ACLK S00_ACLK S01_ACLK M00_ACLK} {
    catch {connect_bd_net $CLK [get_bd_pins hp3_merge/$p]}
}
foreach p {ARESETN S00_ARESETN S01_ARESETN M00_ARESETN} {
    catch {connect_bd_net $RST [get_bd_pins hp3_merge/$p]}
}
catch {connect_bd_net $CLK [get_bd_pins ps7_0_axi_periph/M16_ACLK]}
catch {connect_bd_net $RST [get_bd_pins ps7_0_axi_periph/M16_ARESETN]}
L "   clocks/resets connected"

# ---- 7. addresses ----
L ""
L ">>> assign addresses"
set sseg ""
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*gpu_0/s_axi*" $s]} { set sseg $s }
}
if {$sseg ne ""} {
    if {[catch {
        assign_bd_address -force -offset 0x43CB0000 -range 64K \
            -target_address_space /processing_system7_0/Data $sseg
    } e3]} {
        L "  !! slave address failed: $e3"
    } else {
        L "   slave $sseg -> 0x43CB0000 / 64K"
    }
} else { L "  !! gpu_0 slave segment not found" }

if {[catch {
    assign_bd_address -force -offset 0x00000000 -range 1G \
        -target_address_space /gpu_0/m_axi \
        [get_bd_addr_segs processing_system7_0/S_AXI_HP3/HP3_DDR_LOWOCM]
} e4]} {
    L "  !! master address failed: $e4"
} else {
    L "   master gpu_0/m_axi -> 0x00000000 / 1G (must NOT be 64K)"
}

# ---- 8. validate / save / generate ----
L ""
L ">>> validate_bd_design"
if {[catch {validate_bd_design} e2]} {
    L " !! BD validation failed: $e2"
    close $LOG
    exit 1
}
L " BD validated"
save_bd_design

L ""
L ">>> generate_target all"
if {[catch {generate_target all [get_files system.bd]} e5]} {
    L " !! generate_target failed: $e5"
    close $LOG
    exit 1
}
L " generated"

# ---- 9. re-check ----
L ""
L "=== addresses ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    set o "?"
    catch {set o [get_property offset $s]}
    if {$o eq "0x43CB0000" || [string match "*gpu_0/m_axi*" $s]} {
        set r "?"; catch {set r [get_property range $s]}
        L "  $s = $o / $r"
    }
}
L ""
L "=== gpu_0 intf pins ==="
foreach p [lsort [get_bd_intf_pins -quiet gpu_0/*]] { L "  $p" }

close $LOG
puts "RESULT=OK"
exit 0
