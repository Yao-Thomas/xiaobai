set PART    xc7z020clg400-2
set ROOT    {D:/FPGA_project/zynq_scpoe_ds}
set IPREPO  [file join $ROOT ip_repo scope_dual_axi]
set TMPPROJ [file join $ROOT _package_project]

proc L {m} { puts "### $m" }

create_project -force scope_dual_package $TMPPROJ -part $PART
add_files -norecurse [list \
    [file join $ROOT rtl scope_dual_core.v] \
    [file join $ROOT rtl scope_dual_axi.v]]
set_property top scope_dual_axi [current_fileset]
update_compile_order -fileset sources_1

if {[file exists $IPREPO]} { file delete -force $IPREPO }
file mkdir $IPREPO
ipx::package_project -root_dir $IPREPO \
    -vendor dsh -library user -taxonomy /UserIP \
    -import_files -set_current false -force
ipx::open_core -quiet [file join $IPREPO component.xml]
set core [ipx::current_core]

set_property name                scope_dual_axi $core
set_property version             1.0 $core
set_property display_name        "Dual 3PA1030 Oscilloscope Capture" $core
set_property description         "Two-channel 10-bit 20-MSPS capture, 4096 points, double buffer, pre-trigger and AXI4-Lite readout" $core
set_property vendor_display_name "DSH" $core

if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==aclk}]] == 0} {
    ipx::infer_bus_interface aclk xilinx.com:signal:clock_rtl:1.0 $core
}
if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==aresetn}]] == 0} {
    ipx::infer_bus_interface aresetn xilinx.com:signal:reset_rtl:1.0 $core
}
if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==sample_clk}]] == 0} {
    ipx::infer_bus_interface sample_clk xilinx.com:signal:clock_rtl:1.0 $core
}
if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==adc_ref_clk}]] == 0} {
    ipx::infer_bus_interface adc_ref_clk xilinx.com:signal:clock_rtl:1.0 $core
}

proc set_bp {iface pname pvalue} {
    if {[llength [ipx::get_bus_parameters -of_objects $iface $pname]] == 0} {
        ipx::add_bus_parameter $pname $iface
    }
    set_property value $pvalue [ipx::get_bus_parameters -of_objects $iface $pname]
}

set clkif [ipx::get_bus_interfaces aclk -of_objects $core]
set_bp $clkif ASSOCIATED_BUSIF {S_AXI}
set_bp $clkif ASSOCIATED_RESET {aresetn}
set_bp $clkif FREQ_HZ {100000000}
set rstif [ipx::get_bus_interfaces aresetn -of_objects $core]
set_bp $rstif POLARITY {ACTIVE_LOW}
set sampleif [ipx::get_bus_interfaces sample_clk -of_objects $core]
set_bp $sampleif FREQ_HZ {20000000}
set adcrefif [ipx::get_bus_interfaces adc_ref_clk -of_objects $core]
set_bp $adcrefif FREQ_HZ {20000000}

set axif [ipx::get_bus_interfaces S_AXI -of_objects $core]
if {$axif eq ""} { set axif [ipx::get_bus_interfaces s_axi -of_objects $core] }
if {$axif eq ""} {
    puts "### FATAL: AXI interface was not inferred"
    exit 2
}
ipx::associate_bus_interfaces -busif [get_property NAME $axif] \
    -clock aclk -reset aresetn $core

ipx::create_xgui_files $core
ipx::update_checksums $core
set check_result [ipx::check_integrity -quiet $core]
L "integrity=$check_result"
ipx::save_core $core
close_project

if {![file exists [file join $IPREPO component.xml]]} {
    puts "### RESULT=PACKAGE_FAIL"
    exit 3
}
puts "### RESULT=PACKAGE_OK"
exit 0
