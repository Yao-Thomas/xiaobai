# package_ip_cpq.tcl —— 打包 cnn_conv_pool_q RTL 为 IP
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hdl_dir     [file join $proj_root build hls_prj_cpq cpq_prj sol1 impl ip hdl verilog]
set pkg_root    [file join $proj_root build ip_repo_cpq]
set pkg_prj_dir [file join $proj_root build pkg_prj_cpq]
file delete -force $pkg_root
file delete -force $pkg_prj_dir
file mkdir $pkg_root
create_project -force pkg_prj_cpq $pkg_prj_dir -part xc7z020clg400-1
add_files [file join $hdl_dir cnn_conv_pool_q.v]
add_files [file join $hdl_dir cnn_conv_pool_q_AXILiteS_s_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_q_gmem_img_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_q_gmem_w_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_q_gmem_out_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_q_mcud.v]
add_files [file join $hdl_dir cnn_conv_pool_q_sbkb.v]
set_property top cnn_conv_pool_q [current_fileset]
ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (cnn_conv_pool_q) ===="
exit
