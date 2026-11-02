# package_ip_cnn2.tcl —— 把 HLS 生成的 cnn_conv1_pool RTL 打包为自定义 IP（规避 core_revision）
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]

set hdl_dir     [file join $proj_root build hls_prj_cnn2 cnn2_prj sol1 impl ip hdl verilog]
set pkg_root    [file join $proj_root build ip_repo_cnn2]
set pkg_prj_dir [file join $proj_root build pkg_prj_cnn2]
file mkdir $pkg_root

create_project -force pkg_prj_cnn2 $pkg_prj_dir -part xc7z020clg400-1
add_files [file join $hdl_dir cnn_conv1_pool.v]
add_files [file join $hdl_dir cnn_conv1_pool_AXILiteS_s_axi.v]
add_files [file join $hdl_dir cnn_conv1_pool_gmem_m_axi.v]
add_files [file join $hdl_dir cnn_conv1_pool_macud.v]
add_files [file join $hdl_dir cnn_conv1_pool_sdbkb.v]

set_property top cnn_conv1_pool [current_fileset]

ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (cnn_conv1_pool) ===="
exit
