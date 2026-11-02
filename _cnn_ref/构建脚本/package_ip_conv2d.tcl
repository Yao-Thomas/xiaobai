# package_ip_conv2d.tcl —— 打包 conv2d_accel 为自定义 IP
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set src         [file join $proj_root src rtl conv2d_accel.v]
set pkg_root    [file join $proj_root build ip_repo_conv2d]
set pkg_prj_dir [file join $proj_root build pkg_prj_conv2d]
file mkdir $pkg_root

create_project -force pkg_prj $pkg_prj_dir -part xc7z020clg400-1
add_files $src

ipx::package_project -import_files -root_dir $pkg_root -library user -vendor user.org
puts "==== IP PACKAGED (conv2d_accel) ===="
exit
