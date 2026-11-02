# package_ip_cnn3.tcl —— 打包 3 端口 cnn_conv_pool RTL 为自定义 IP
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hdl_dir     [file join $proj_root build hls_prj_cnn3 cnn3_prj sol1 impl ip hdl verilog]
set pkg_root    [file join $proj_root build ip_repo_cnn3]
set pkg_prj_dir [file join $proj_root build pkg_prj_cnn3]
file delete -force $pkg_root
file delete -force $pkg_prj_dir
file mkdir $pkg_root
create_project -force pkg_prj_cnn3 $pkg_prj_dir -part xc7z020clg400-1
add_files [file join $hdl_dir cnn_conv_pool.v]
add_files [file join $hdl_dir cnn_conv_pool_AXILiteS_s_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_gmem_img_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_gmem_w_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_gmem_out_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool_maccud.v]
add_files [file join $hdl_dir cnn_conv_pool_sdibkb.v]
set_property top cnn_conv_pool [current_fileset]
ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (cnn_conv_pool 3port) ===="
exit
