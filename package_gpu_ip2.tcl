#=====================================================================
#  package_gpu_ip2.tcl —— 重新打包 GPU IP (修复: AXI 接口必须关联时钟)
#  用法: vivado -mode batch -source package_gpu_ip2.tcl
#=====================================================================
set PART   xc7z020clg400-2
set SRC    {D:/ubuntu_iso/gpu_ip/src}
set IPREPO {D:/ubuntu_iso/gpu_ip2}

puts "======================================================"
puts " 重新打包 GPU IP (Vivado [version -short])"
puts "======================================================"

# 清空输出目录(保留 src 的复制)
file mkdir $IPREPO

create_project -force gpu2d_ip {D:/ubuntu_iso/_ip_proj2} -part $PART
add_files -norecurse [list "$SRC/gpu2d.v" "$SRC/gpu2d_axi.v"]
set_property top gpu2d_axi [current_fileset]
update_compile_order -fileset sources_1

# ---- 打包 ----
ipx::package_project -root_dir $IPREPO \
    -vendor dsh -library user -taxonomy /UserIP \
    -import_files -set_current false -force

# 重新打开(不带 -set_current 时要显式打开)
ipx::open_core -quiet $IPREPO/component.xml
set core [ipx::current_core]

set_property display_name        "GPU 2D Accelerator (gpu2d)" $core
set_property description         "简易 2D 图形加速器: 矩形填充 + Bresenham 直线; AXI4-Lite 控制 + AXI4 主机突发写 DDR" $core
set_property vendor_display_name "DSH" $core
set_property company_url         "https://example.local" $core
set_property version             "1.0" $core

# ---- 列出已有总线接口 (看真实名字) ----
puts ""
puts "--- 打包后的总线接口 ---"
foreach bi [ipx::get_bus_interfaces -of_objects $core] {
    puts "    [get_property name $bi]  ($bi)"
}

# ---- 1. 把 aclk / aresetn 推断成 时钟/复位 信号接口 ----
if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==aclk}]] == 0} {
    ipx::infer_bus_interface aclk    xilinx.com:signal:clock_rtl:1.0  $core
}
if {[llength [ipx::get_bus_interfaces -of_objects $core -filter {NAME==aresetn}]] == 0} {
    ipx::infer_bus_interface aresetn xilinx.com:signal:reset_rtl:1.0  $core
}
puts " ✅ aclk/aresetn 已推断为时钟/复位接口"

# ---- 2. 给时钟接口设参数: 关联总线 + 复位 + 100MHz ----
set clkif [ipx::get_bus_interfaces aclk -of_objects $core]
proc set_bp {iface pname pvalue} {
    if {[llength [ipx::get_bus_parameters -of_objects $iface $pname]] == 0} {
        ipx::add_bus_parameter $pname $iface
    }
    set_property value $pvalue [ipx::get_bus_parameters -of_objects $iface $pname]
}
set_bp $clkif ASSOCIATED_BUSIF {S_AXI:M_AXI}
set_bp $clkif ASSOCIATED_RESET {aresetn}
puts " ✅ 时钟已关联总线 S_AXI:M_AXI 和复位 aresetn"

set rstif [ipx::get_bus_interfaces aresetn -of_objects $core]
set_bp $rstif POLARITY {ACTIVE_LOW}
puts " ✅ 复位极性 = ACTIVE_LOW"

# ---- 3. 把 AXI 接口显式关联到 aclk ----
foreach biname {S_AXI M_AXI} {
    set bi [ipx::get_bus_interfaces $biname -of_objects $core]
    if {$bi eq ""} {
        puts " ⚠️ 找不到接口 $biname"
    } else {
        ipx::associate_bus_interfaces -busif $biname -clock aclk -reset aresetn $core
        puts " ✅ $biname 已关联 aclk/aresetn"
    }
}

# ---- 4. 保存 ----
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project

# ---- 5. 验证 ----
set t [read_file "$IPREPO/component.xml"]
puts ""
puts "--- 验证 component.xml ---"
foreach pat {ASSOCIATED_BUSIF ASSOCIATED_RESET signal:clock_rtl signal:reset_rtl} {
    set n [regexp -all $pat $t]
    puts "    $pat : $n 次"
}
puts ""
puts "======================================================"
puts " ✅ 打包完成: $IPREPO"
puts "======================================================"
exit 0
