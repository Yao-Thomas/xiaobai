# package_ip_fcq.tcl —— 打包 cnn_fc_q RTL 为 IP
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hdl_dir     [file join $proj_root build hls_prj_fcq fcq_prj sol1 impl ip hdl verilog]
set pkg_root    [file join $proj_root build ip_repo_fcq]
set pkg_prj_dir [file join $proj_root build pkg_prj_fcq]
file delete -force $pkg_root
file delete -force $pkg_prj_dir
file mkdir $pkg_root
create_project -force pkg_prj_fcq $pkg_prj_dir -part xc7z020clg400-1
add_files [file join $hdl_dir cnn_fc_q.v]
add_files [file join $hdl_dir cnn_fc_q_AXILiteS_s_axi.v]
add_files [file join $hdl_dir cnn_fc_q_gmem_x_m_axi.v]
add_files [file join $hdl_dir cnn_fc_q_gmem_w_m_axi.v]
add_files [file join $hdl_dir cnn_fc_q_gmem_out_m_axi.v]
add_files [file join $hdl_dir cnn_fc_q_mac_mulabkb.v]
set_property top cnn_fc_q [current_fileset]
ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (cnn_fc_q) ===="
exit
