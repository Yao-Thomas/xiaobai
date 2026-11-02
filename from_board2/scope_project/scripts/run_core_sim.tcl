set ROOT {D:/FPGA_project/zynq_scpoe_ds}
set PROJ [file join $ROOT _sim_project]

create_project -force scope_dual_sim $PROJ -part xc7z020clg400-2
add_files -norecurse [file join $ROOT rtl scope_dual_core.v]
add_files -fileset sim_1 -norecurse [file join $ROOT sim tb_scope_dual_core.v]
set_property top tb_scope_dual_core [get_filesets sim_1]
update_compile_order -fileset sources_1
update_compile_order -fileset sim_1
launch_simulation -simset sim_1 -mode behavioral
run all
close_sim
close_project
puts "RESULT=SIM_OK"
exit 0
