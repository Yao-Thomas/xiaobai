# package_ip_fc.tcl —— 打包 cnn_fc RTL 为自定义 IP
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hdl_dir     [file join $proj_root build hls_prj_fc fc_prj sol1 impl ip hdl verilog]
set pkg_root    [file join $proj_root build ip_repo_fc]
set pkg_prj_dir [file join $proj_root build pkg_prj_fc]
file delete -force $pkg_root
file delete -force $pkg_prj_dir
file mkdir $pkg_root
create_project -force pkg_prj_fc $pkg_prj_dir -part xc7z020clg400-1
add_files [file join $hdl_dir cnn_fc.v]
add_files [file join $hdl_dir cnn_fc_AXILiteS_s_axi.v]
add_files [file join $hdl_dir cnn_fc_gmem_x_m_axi.v]
add_files [file join $hdl_dir cnn_fc_gmem_w_m_axi.v]
add_files [file join $hdl_dir cnn_fc_gmem_out_m_axi.v]
add_files [file join $hdl_dir cnn_fc_mac_muladdbkb.v]
set_property top cnn_fc [current_fileset]
ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (cnn_fc) ===="
exit
