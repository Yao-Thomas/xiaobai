set ROOT      {D:/FPGA_project/zynq_scpoe_ds}
set BASE      {D:/FPGA_project/zynq01/fpga2018}
set STAGE     [file join $BASE bd_src]
set ATKREPO   [file join $BASE atk_ip]
set GPUREPO   [file join $BASE gpu_ip]
set SCOPEREPO [file join $ROOT ip_repo scope_dual_axi]
set PROJ      [file join $ROOT vivado]
set BDROOT    [file join $PROJ scope_zynq.srcs sources_1 bd system]
set XDCDIR    [file join $PROJ scope_zynq.srcs constrs_1]
set OUT       [file join $ROOT out]

proc L {m} { puts "### $m" }
proc T {} { return [clock format [clock seconds] -format "%H:%M:%S"] }

if {![file exists [file join $SCOPEREPO component.xml]]} {
    puts "### FATAL: package the scope IP first"
    exit 2
}

create_project -force scope_zynq $PROJ -part xc7z020clg400-2
set_property ip_repo_paths [list $ATKREPO $GPUREPO $SCOPEREPO] [current_project]
update_ip_catalog -rebuild
L "fresh project and IP catalog ready"

file mkdir $BDROOT
file mkdir $XDCDIR
file mkdir $OUT
foreach item [glob -nocomplain [file join $STAGE system *]] {
    file copy -force $item [file join $BDROOT [file tail $item]]
}
file copy -force [file join $ROOT constraints scope_dual.xdc] \
                 [file join $XDCDIR scope_dual.xdc]
add_files -norecurse [file join $BDROOT system.bd]
add_files -fileset constrs_1 -norecurse [file join $XDCDIR scope_dual.xdc]
update_compile_order -fileset sources_1
open_bd_design [get_files system.bd]
L "base block design opened"

# Camera and HDMI are not used by the oscilloscope image.  Removing HDMI also
# removes its high-speed 5x pixel clock, which was the old design's pulse-width
# timing violation.
foreach cell {camera_in hdmi_out i2c2} {
    if {[llength [get_bd_cells -quiet $cell]] > 0} {
        delete_bd_objs [get_bd_cells $cell]
        L "removed $cell"
    }
}
catch {set_property -dict [list CONFIG.PCW_USE_S_AXI_HP1 {0}] \
       [get_bd_cells processing_system7_0]}

# Remove external interfaces that occupy the selected J11 ADC pins.
# The audio processing path itself is retained so the existing Linux image and
# address map remain compatible; only its board pins are removed.
foreach intf {can0 i2c0 i2c2 pl_led tmds uart1} {
    foreach obj [get_bd_intf_ports -quiet $intf] {
        catch {delete_bd_objs $obj}
        L "removed external interface $intf"
    }
}
foreach pat {aud_* cmos_* can0_* i2c0_* i2c2_* pl_led_* tmds_* uart1_*} {
    foreach obj [get_bd_ports -quiet $pat] {
        catch {delete_bd_objs $obj}
    }
}

# Tie off interrupt inputs whose producers were removed.
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 removed_tie0
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {0}] \
    [get_bd_cells removed_tie0]
foreach pin {xlconcat_0/In2 xlconcat_0/In3 xlconcat_0/In8 xlconcat_0/In9} {
    if {[llength [get_bd_pins -quiet $pin]] > 0} {
        foreach oldnet [get_bd_nets -quiet -of_objects [get_bd_pins $pin]] {
            catch {delete_bd_objs $oldnet}
        }
        connect_bd_net [get_bd_pins removed_tie0/dout] [get_bd_pins $pin]
    }
}

# Audio ADC data was an external input.  Keep the subsystem valid without
# consuming a J11 pin by tying the unused input low.
if {[llength [get_bd_pins -quiet audio/aud_adcdat]] > 0} {
    foreach oldnet [get_bd_nets -quiet -of_objects [get_bd_pins audio/aud_adcdat]] {
        catch {delete_bd_objs $oldnet}
    }
    connect_bd_net [get_bd_pins removed_tie0/dout] [get_bd_pins audio/aud_adcdat]
}

# Re-clock any still-present interconnect input that used the deleted HDMI
# pixel clock.  An unused M14 output is harmless but its clock/reset cannot
# float in an AXI interconnect.
foreach pin {ps7_0_axi_periph/M14_ACLK processing_system7_0/S_AXI_HP1_ACLK} {
    if {[llength [get_bd_pins -quiet $pin]] > 0} {
        foreach oldnet [get_bd_nets -quiet -of_objects [get_bd_pins $pin]] {
            catch {delete_bd_objs $oldnet}
        }
        catch {connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
                              [get_bd_pins $pin]}
    }
}
if {[llength [get_bd_pins -quiet ps7_0_axi_periph/M14_ARESETN]] > 0} {
    foreach oldnet [get_bd_nets -quiet -of_objects \
                    [get_bd_pins ps7_0_axi_periph/M14_ARESETN]] {
        catch {delete_bd_objs $oldnet}
    }
    catch {connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] \
                          [get_bd_pins ps7_0_axi_periph/M14_ARESETN]}
}
if {[llength [get_bd_pins -quiet ps7_0_axi_periph/M05_ARESETN]] > 0} {
    foreach oldnet [get_bd_nets -quiet -of_objects \
                    [get_bd_pins ps7_0_axi_periph/M05_ARESETN]] {
        catch {delete_bd_objs $oldnet}
    }
    catch {connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] \
                          [get_bd_pins ps7_0_axi_periph/M05_ARESETN]}
}

# Two related 20 MHz clocks derived from the 100 MHz PS fabric clock:
# clk_out1 is forwarded to both ADCs; clk_out2 is shifted 270 degrees so
# input data is captured 37.5 ns after the ADC rising edge. AD9200-compatible
# parts specify about 25 ns clock-to-data delay, leaving useful margin on
# both sides of the FPGA capture edge.
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 scope_adc_clk
set_property -dict [list \
    CONFIG.PRIM_IN_FREQ {100.000} \
    CONFIG.NUM_OUT_CLKS {2} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {20.000} \
    CONFIG.CLKOUT2_USED {true} \
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {20.000} \
    CONFIG.CLKOUT2_REQUESTED_PHASE {270.000} \
    CONFIG.USE_RESET {false} \
    CONFIG.USE_LOCKED {false}] [get_bd_cells scope_adc_clk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins scope_adc_clk/clk_in1]

# Add the dual-channel scope AXI slave.
create_bd_cell -type ip -vlnv dsh:user:scope_dual_axi:1.0 scope_dual_0
set_property -dict [list CONFIG.NUM_MI {18}] [get_bd_cells ps7_0_axi_periph]
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M17_AXI] \
                    [get_bd_intf_pins scope_dual_0/S_AXI]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins scope_dual_0/aclk] \
               [get_bd_pins ps7_0_axi_periph/M17_ACLK]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] \
               [get_bd_pins scope_dual_0/aresetn] \
               [get_bd_pins ps7_0_axi_periph/M17_ARESETN]
connect_bd_net [get_bd_pins scope_adc_clk/clk_out1] \
               [get_bd_pins scope_dual_0/adc_ref_clk]
connect_bd_net [get_bd_pins scope_adc_clk/clk_out2] \
               [get_bd_pins scope_dual_0/sample_clk]

# Physical ADC ports.
# J4 (BANK13 + B34 camera group) carries all 26 ADC signals and does not touch
# any LCD pin.  gpio0_tri_io[7]/[10] were moved to J14/K14 in the XDC to free
# V15 and U13 for the ADC.
create_bd_port -dir I -from 9 -to 0 adc1_data
create_bd_port -dir I -from 9 -to 0 adc2_data
create_bd_port -dir O -type clk adc1_clk
create_bd_port -dir O -type clk adc2_clk
connect_bd_net [get_bd_ports adc1_data] [get_bd_pins scope_dual_0/adc1_data]
connect_bd_net [get_bd_ports adc2_data] [get_bd_pins scope_dual_0/adc2_data]
connect_bd_net [get_bd_ports adc1_clk] [get_bd_pins scope_dual_0/adc1_clk]
connect_bd_net [get_bd_ports adc2_clk] [get_bd_pins scope_dual_0/adc2_clk]

# ADC output-enable. The 3PA1030 OE is active LOW: it MUST be driven low or the
# module leaves its data bus high-Z and the FPGA reads junk. 正点原子's own
# example does "assign ad0_oe = 1'b0".  OE shares the J4 header with the ADC.
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 adc_oe_low
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {0}] \
    [get_bd_cells adc_oe_low]
create_bd_port -dir O adc1_oe
create_bd_port -dir O adc2_oe
connect_bd_net [get_bd_pins adc_oe_low/dout] [get_bd_ports adc1_oe]
connect_bd_net [get_bd_pins adc_oe_low/dout] [get_bd_ports adc2_oe]

set scope_seg ""
foreach seg [get_bd_addr_segs -quiet] {
    if {[string match "*scope_dual_0/S_AXI*" $seg]} { set scope_seg $seg }
}
if {$scope_seg eq ""} {
    puts "### FATAL: scope address segment not found"
    exit 3
}
assign_bd_address -offset 0x43CC0000 -range 64K \
    -target_address_space /processing_system7_0/Data $scope_seg
L "scope mapped at 0x43CC0000"

save_bd_design
if {[catch {validate_bd_design} validation_error]} {
    puts "### VALIDATE_FAIL: $validation_error"
    exit 4
}
puts "### VALIDATE_OK"

set bd [get_files system.bd]
reset_target all $bd
generate_target all $bd
save_bd_design

# Vivado 2018.3 does not regenerate this HLS frame-buffer RTL reliably on a
# modern host date.  The known-good generated RTL is cached with this project
# so the LCD path remains reproducible.
set lcd_hls_cache [file join $ROOT vendor_cache system_v_frmbuf_rd_0_1_1 hdl verilog]
if {![file isdirectory $lcd_hls_cache]} {
    puts "### FATAL: LCD HLS cache missing: $lcd_hls_cache"
    exit 4
}
set lcd_hls_sources [concat \
    [glob -nocomplain [file join $lcd_hls_cache *.v]] \
    [glob -nocomplain [file join $lcd_hls_cache *.dat]]]
add_files -norecurse $lcd_hls_sources
set_property source_mgmt_mode None [current_project]
L "added [llength $lcd_hls_sources] cached LCD HLS files"

set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
L "wrapper ready; in-process synthesis starts at [T]"

# Run in the current Vivado process.  This is deterministic on Windows hosts
# where the normal launch_runs helper may be blocked from spawning cscript.
if {[catch {synth_design -top system_wrapper -part xc7z020clg400-2} synth_error]} {
    puts "### RESULT=SYNTH_FAIL: $synth_error"
    exit 5
}
write_checkpoint -force [file join $OUT post_synth.dcp]
report_utilization -file [file join $OUT utilization_synth.rpt]
L "synthesis complete at [T]"

if {[catch {
    opt_design
    place_design
    phys_opt_design
    route_design
} impl_error]} {
    puts "### RESULT=IMPL_FAIL: $impl_error"
    exit 6
}
write_checkpoint -force [file join $OUT post_route.dcp]
set final_bit [file join $OUT system_scope_dual.bit]
if {[catch {write_bitstream -force $final_bit} bit_error]} {
    puts "### RESULT=BIT_FAIL: $bit_error"
    exit 7
}

report_timing_summary -file [file join $OUT timing_summary.rpt]
report_utilization -file [file join $OUT utilization.rpt]
report_drc -file [file join $OUT drc.rpt]
puts "### BIT=$final_bit ([file size $final_bit] bytes)"

set timing_ok 0
set timing_text ""
set timing_file [file join $OUT timing_summary.rpt]
if {[file exists $timing_file]} {
    set fh [open $timing_file r]
    set timing_text [read $fh]
    close $fh
    if {[string match "*All user specified timing constraints are met*" $timing_text]} {
        set timing_ok 1
    }
}
puts "### TIMING_MET=$timing_ok"
puts "### RESULT=BIT_OK"
exit 0
