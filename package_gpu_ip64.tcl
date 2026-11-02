#=====================================================================
#  package_gpu_ip64.tcl —— 重新打包 GPU IP: AXI 写通路 1 字节/拍 -> 8 字节/拍
#    源: D:/ubuntu_iso/gpu_ip_src_new/gpu2d_axi.v (64 位, awsize=3'b011)
#    输出: D:/ubuntu_iso/gpu_ip   (工程 xpr 里 IPRepoPath 指向的就是这里)
#  用法: vivado -mode batch -source package_gpu_ip64.tcl
#=====================================================================
set PART   xc7z020clg400-2
set SRC    {D:/ubuntu_iso/gpu_ip_src_new}
set IPREPO {D:/ubuntu_iso/gpu_ip}

puts "======================================================"
puts " 打包 64 位 GPU IP (Vivado [version -short])"
puts "======================================================"

# 先做个备份, 万一打包坏了能退回
set BAK "$IPREPO.bak_1byte"
if {![file exists $BAK]} {
    file copy -force $IPREPO $BAK
    puts " 已备份原 IP 仓库 -> $BAK"
} else {
    puts " 备份已存在: $BAK"
}

create_project -force gpu2d_ip64 {D:/ubuntu_iso/_ip_proj64} -part $PART
add_files -norecurse [list "$SRC/gpu2d.v" "$SRC/gpu2d_axi.v"]
set_property top gpu2d_axi [current_fileset]
update_compile_order -fileset sources_1

# ---- 打包 (源在别处, -import_files 会拷进 $IPREPO/src) ----
ipx::package_project -root_dir $IPREPO \
    -vendor dsh -library user -taxonomy /UserIP \
    -import_files -set_current false -force

ipx::open_core -quiet $IPREPO/component.xml
set core [ipx::current_core]

set_property display_name        "GPU 2D Accelerator (gpu2d)" $core
set_property description         "简易 2D 图形加速器: 矩形填充 + Bresenham 直线; AXI4-Lite 控制 + AXI4 64位主机突发写 DDR (8字节/拍)" $core
set_property vendor_display_name "DSH" $core
set_property company_url         "https://example.local" $core
set_property version             "1.0" $core

# ---- 时钟 / 复位接口 ----
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
set_bp $clkif ASSOCIATED_BUSIF {S_AXI:M_AXI}
set_bp $clkif ASSOCIATED_RESET {aresetn}

set rstif [ipx::get_bus_interfaces aresetn -of_objects $core]
set_bp $rstif POLARITY {ACTIVE_LOW}

foreach biname {S_AXI M_AXI} {
    set bi [ipx::get_bus_interfaces $biname -of_objects $core]
    if {$bi eq ""} {
        puts " !! 找不到接口 $biname"
    } else {
        ipx::associate_bus_interfaces -busif $biname -clock aclk -reset aresetn $core
        puts " OK $biname 已关联 aclk/aresetn"
    }
}

ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project

# ---- 验证 component.xml 里 M_AXI 的位宽 ----
puts ""
puts "--- 验证 component.xml ---"
set t [read_file "$IPREPO/component.xml"]
set nw64 [regexp -all {m_axi_wdata} $t]
puts "    m_axi_wdata 出现 $nw64 次"
foreach {pat want} {ASSOCIATED_BUSIF 1 ASSOCIATED_RESET 1 signal:clock_rtl 1 signal:reset_rtl 1} {
    set n [regexp -all $pat $t]
    puts "    $pat : $n 次"
}
puts ""
puts "--- 源文件确认 ---"
foreach f {gpu2d.v gpu2d_axi.v} {
    set p "$IPREPO/src/$f"
    if {[file exists $p]} {
        puts "    $p  [file size $p] 字节"
    } else {
        puts "    !! 缺少 $p"
    }
}
set ax [read_file "$IPREPO/src/gpu2d_axi.v"]
puts "    awsize 行: [regexp -inline {assign m_axi_awsize[^\n]*} $ax]"
puts "    wdata  行: [regexp -inline {output wire \[[0-9]+:0\][^\n]*m_axi_wdata} $ax]"
puts ""
puts "======================================================"
puts " 打包完成: $IPREPO"
puts "======================================================"
exit 0
