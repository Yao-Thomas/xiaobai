#=====================================================================
#  bd_scope.tcl -- add the scope capture IP into the block design
#    · scope_0/s_axi -> ps7_0_axi_periph/M17_AXI   (NUM_MI 17 -> 18)
#    · address 0x43CC0000 / 64K
#    · adc_data tied to 0 for now (V1 uses the internal DDS source)
#    · adc_clk / adc_dbg left unconnected (V2 will bring them to pins)
#  usage: vivado -mode batch -source bd_scope.tcl
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/bd_scope_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " add scope_cap IP into BD"
L " time: [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ

# ---- 1. add IP repo ----
set cur [get_property ip_repo_paths [current_project]]
L "current ip_repo_paths: $cur"
if {[lsearch $cur {D:/ubuntu_iso/scope_ip}] < 0} {
    set_property ip_repo_paths [concat $cur {D:/ubuntu_iso/scope_ip}] [current_project]
    L " added D:/ubuntu_iso/scope_ip"
} else {
    L " scope_ip already in ip_repo_paths"
}
update_ip_catalog -rebuild
foreach d [get_ipdefs -quiet *scope_cap*] { L "  found IP: $d" }

open_bd_design [get_files system.bd]
L " BD opened"

# ---- 2. remove old instance if re-running ----
if {[llength [get_bd_cells -quiet scope_0]] > 0} {
    catch {delete_bd_objs [get_bd_cells scope_0]}
    L " removed old scope_0"
}
if {[llength [get_bd_cells -quiet scope_tie]] > 0} {
    catch {delete_bd_objs [get_bd_cells scope_tie]}
    L " removed old scope_tie"
}

# ---- 3. create the cell ----
L ""
L ">>> create scope_0"
if {[catch {create_bd_cell -type ip -vlnv dsh:user:scope_cap_axi:1.0 scope_0} e1]} {
    L " !! create scope_0 failed: $e1"
    close $LOG
    exit 1
}
L "  scope_0 created"
L "  intf pins:"
foreach p [lsort [get_bd_intf_pins -quiet scope_0/*]] { L "     $p" }
L "  plain pins:"
foreach p [lsort [get_bd_pins -quiet scope_0/*]] { L "     $p" }

# ---- 4. tie adc_data to 0 ----
L ""
L ">>> tie adc_data to constant 0 (V1 = internal DDS source)"
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 scope_tie
set_property -dict [list CONFIG.CONST_WIDTH {8} CONFIG.CONST_VAL {0}] [get_bd_cells scope_tie]
connect_bd_net [get_bd_pins scope_tie/dout] [get_bd_pins scope_0/adc_data]
L "  adc_data <- const 0"

# ---- 5. AXI-Lite slave -> ps7_0_axi_periph M17 ----
L ""
L ">>> connect AXI-Lite"
set_property -dict [list CONFIG.NUM_MI {18}] [get_bd_cells ps7_0_axi_periph]
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M17_AXI] [get_bd_intf_pins scope_0/s_axi]
L "  ps7_0_axi_periph/M17 -> scope_0/s_axi  (NUM_MI=18)"

# ---- 6. clocks / resets ----
set CLK [get_bd_pins processing_system7_0/FCLK_CLK0]
set RST [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]
catch {connect_bd_net $CLK [get_bd_pins scope_0/aclk]}
catch {connect_bd_net $RST [get_bd_pins scope_0/aresetn]}
catch {connect_bd_net $CLK [get_bd_pins scope_tie/dout]}
catch {connect_bd_net $CLK [get_bd_pins ps7_0_axi_periph/M17_ACLK]}
catch {connect_bd_net $RST [get_bd_pins ps7_0_axi_periph/M17_ARESETN]}
L "  clocks/resets connected"

# ---- 7. address ----
L ""
L ">>> assign address"
set sseg ""
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*scope_0/s_axi*" $s]} { set sseg $s }
}
if {$sseg ne ""} {
    if {[catch {
        assign_bd_address -force -offset 0x43CC0000 -range 64K \
            -target_address_space /processing_system7_0/Data $sseg
    } e3]} {
        L "  !! slave address failed: $e3"
    } else {
        L "   slave $sseg -> 0x43CC0000 / 64K"
    }
} else { L "  !! scope_0 slave segment not found" }

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

# ---- 9. re-check addresses ----
L ""
L "=== addresses (scope/gpu) ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    set o "?"
    catch {set o [get_property offset $s]}
    if {$o eq "0x43CC0000" || $o eq "0x43CB0000"} {
        set r "?"; catch {set r [get_property range $s]}
        L "  $s = $o / $r"
    }
}
close $LOG
puts "RESULT=OK"
exit 0
