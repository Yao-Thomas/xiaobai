# ============================================================================
# package_ip.tcl —— 把自定义 AXI 加速器打包成 Vivado 自定义 IP
# 打包后放到 build/ip_repo，供 Block Design 用 -type ip -vlnv 引用。
# ============================================================================
set script_dir [file dirname [file normalize [info script]]]
set proj_root   [file normalize [file join $script_dir ..]]
set src         [file join $proj_root src rtl conv_accel_axi_lite.v]
set pkg_root    [file join $proj_root build ip_repo]
set pkg_prj_dir [file join $proj_root build pkg_prj]
file mkdir $pkg_root

create_project -force pkg_prj $pkg_prj_dir -part xc7z020clg400-1
add_files $src

# 打包为自定义 IP
ipx::package_project -import_files -root_dir $pkg_root -library user \
    -vendor user.org

set_property core_revision 16 [ipx::current_components]
ipx::merge_project_changes -component [ipx::current_components]
ipx::create_xgui_files -component [ipx::current_components]
ipx::update_checksums -component [ipx::current_components]
ipx::save_xml -component [ipx::current_components]

puts "==== IP PACKAGED ===="
exit
