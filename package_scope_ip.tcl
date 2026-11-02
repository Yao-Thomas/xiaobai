#=====================================================================
#  package_scope_ip.tcl -- package the scope capture IP (dsh:user:scope_cap:1.0)
#  source : D:/ubuntu_iso/scope_ip/src
#  output : D:/ubuntu_iso/scope_ip   (component.xml + src)
#  usage  : vivado -mode batch -source package_scope_ip.tcl
#=====================================================================
set PART   xc7z020clg400-2
set SRC    {D:/ubuntu_iso/scope_ip_src}
set IPREPO {D:/ubuntu_iso/scope_ip}

puts "======================================================"
puts " package scope_cap IP (Vivado [version -short])"
puts "======================================================"

create_project -force scope_ip_proj {D:/ubuntu_iso/_scope_ip_proj} -part $PART
add_files -norecurse [list "$SRC/scope_cap.v" "$SRC/scope_cap_axi.v"]
set_property top scope_cap_axi [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project -root_dir $IPREPO \
    -vendor dsh -library user -taxonomy /UserIP \
    -import_files -set_current false -force

ipx::open_core -quiet $IPREPO/component.xml
set core [ipx::current_core]

set_property display_name        "Scope Capture (scope_cap)" $core
set_property description         "数字示波器采集器: 4096x8 双 bank 环形缓冲 + 触发电平/边沿/模式 + 预触发 + 抽取; 信号源可选内部 DDS 或外部 8 位并行 ADC" $core
set_property vendor_display_name "DSH" $core
set_property company_url         "https://example.local" $core

if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==aclk}]] == 0} {
    ipx::infer_bus_interface aclk    xilinx.com:signal:clock_rtl:1.0  $core
}
if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==aresetn}]] == 0} {
    ipx::infer_bus_interface aresetn xilinx.com:signal:reset_rtl:1.0  $core
}

set clkif [ipx::get_bus_interfaces aclk -of_objects $core]
proc set_bp {iface pname pvalue} {
    if {[llength [ipx::get_bus_parameters -of_objects $iface $pname]] == 0} {
        ipx::add_bus_parameter $pname $iface
    }
    set_property value $pvalue [ipx::get_bus_parameters -of_objects $iface $pname]
}
set_bp $clkif ASSOCIATED_BUSIF {S_AXI}
set_bp $clkif ASSOCIATED_RESET {aresetn}

set rstif [ipx::get_bus_interfaces aresetn -of_objects $core]
set_bp $rstif POLARITY {ACTIVE_LOW}

foreach biname {S_AXI} {
    set bi [ipx::get_bus_interfaces $biname -of_objects $core]
    if {$bi eq ""} {
        puts " !! interface $biname not found"
    } else {
        ipx::associate_bus_interfaces -busif $biname -clock aclk -reset aresetn $core
        puts " OK $biname associated with aclk/aresetn"
    }
}

ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project

puts ""
puts "--- files in IP repo ---"
foreach f {scope_cap.v scope_cap_axi.v component.xml} {
    set p "$IPREPO/$f"
    if {[file exists $p]} {
        puts "    $p  [file size $p] bytes"
    } else {
        set p "$IPREPO/src/$f"
        if {[file exists $p]} { puts "    $p  [file size $p] bytes" } else { puts "    !! missing $f" }
    }
}
puts ""
puts "======================================================"
puts " packaged: $IPREPO"
puts "======================================================"
exit 0
