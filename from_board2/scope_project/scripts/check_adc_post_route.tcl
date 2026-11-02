set ROOT {D:/FPGA_project/zynq_scpoe_ds}
set DCP  [file join $ROOT out post_route.dcp]
set OUT  [file join $ROOT out]

open_checkpoint $DCP

set adc_clk [get_clocks -quiet clk_out1_system_scope_adc_clk_0]
set adc_ports [get_ports -quiet {adc1_data[*] adc2_data[*]}]
if {[llength $adc_clk] != 1 || [llength $adc_ports] != 20} {
    puts "RESULT=ADC_TIMING_OBJECTS_MISSING clock=[llength $adc_clk] ports=[llength $adc_ports]"
    exit 2
}

set_input_delay -clock $adc_clk -max 25.000 $adc_ports
set_input_delay -clock $adc_clk -min 0.000  $adc_ports

report_timing -from $adc_ports -delay_type max -max_paths 20 \
    -file [file join $OUT adc_input_setup.rpt]
report_timing -from $adc_ports -delay_type min -max_paths 20 \
    -file [file join $OUT adc_input_hold.rpt]
report_timing_summary -file [file join $OUT timing_summary_adc_constrained.rpt]

set setup_paths [get_timing_paths -quiet -from $adc_ports -delay_type max -max_paths 20]
set hold_paths  [get_timing_paths -quiet -from $adc_ports -delay_type min -max_paths 20]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {
    puts "RESULT=ADC_TIMING_PATHS_MISSING setup=[llength $setup_paths] hold=[llength $hold_paths]"
    exit 3
}

set setup_slack [get_property SLACK [lindex $setup_paths 0]]
set hold_slack  [get_property SLACK [lindex $hold_paths 0]]
puts "ADC_SETUP_WORST_SLACK_NS=$setup_slack"
puts "ADC_HOLD_WORST_SLACK_NS=$hold_slack"

if {$setup_slack < 0.0 || $hold_slack < 0.0} {
    puts "RESULT=ADC_TIMING_FAIL"
    exit 4
}

puts "RESULT=ADC_TIMING_OK"
exit 0
