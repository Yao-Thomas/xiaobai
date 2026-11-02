# package_ip_cnn3b.tcl —— 打包 cnn_conv_pool2（常量维度）RTL 为自定义 IP
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set hdl_dir     [file join $proj_root build hls_prj_cnn3b cnn3b_prj sol1 impl ip hdl verilog]
set pkg_root    [file join $proj_root build ip_repo_cnn3b]
set pkg_prj_dir [file join $proj_root build pkg_prj_cnn3b]
file delete -force $pkg_root
file delete -force $pkg_prj_dir
file mkdir $pkg_root
create_project -force pkg_prj_cnn3b $pkg_prj_dir -part xc7z020clg400-1
add_files [file join $hdl_dir cnn_conv_pool2.v]
add_files [file join $hdl_dir cnn_conv_pool2_AXILiteS_s_axi.v]
add_files [file join $hdl_dir cnn_conv_pool2_gmem_img_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool2_gmem_w_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool2_gmem_out_m_axi.v]
add_files [file join $hdl_dir cnn_conv_pool2_macud.v]
add_files [file join $hdl_dir cnn_conv_pool2_ambkb.v]
set_property top cnn_conv_pool2 [current_fileset]
ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (cnn_conv_pool2) ===="
exit
