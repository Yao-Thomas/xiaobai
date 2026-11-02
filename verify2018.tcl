#=====================================================================
#  verify2018.tcl —— 确认 2018.3 里的 BD 是否完整可用
#=====================================================================
set SRC {D:/ubuntu_iso/tmp_try2018/Navigator_7020}
set NEW {D:/ubuntu_iso/tmp_try2018/atk2018b}
if {[file exists $NEW]} { file delete -force $NEW }
create_project -force atk2018b $NEW -part xc7z020clg400-2
set_property ip_repo_paths [list $SRC/ip_repo] [current_project]
update_ip_catalog -rebuild
add_files -norecurse $SRC/Navigator_7020.srcs/sources_1/bd/system/system.bd
update_compile_order -fileset sources_1

set RES [open "D:/ubuntu_iso/verify2018_result.txt" w]
puts $RES "=== BD 内容检查 (Vivado [version -short]) ==="

if {[catch {open_bd_design [get_files system.bd]} err]} {
    puts $RES "OPEN=FAIL $err"
    close $RES
    exit 1
}
puts $RES "OPEN=OK"

# 实例
set cells [get_bd_cells]
puts $RES "CELLCOUNT=[llength $cells]"
foreach c $cells {
    set nm [get_property NAME $c]
    set vl [get_property VLNV $c]
    puts $RES "  CELL $nm  ($vl)"
}

# 关键端口 (GPU 集成要用的)
puts $RES ""
puts $RES "=== 关键接口 ==="
foreach p {processing_system7_0/M_AXI_GP0 processing_system7_0/S_AXI_HP0
           processing_system7_0/S_AXI_HP1 processing_system7_0/S_AXI_HP2
           processing_system7_0/S_AXI_HP3} {
    set ip [get_bd_intf_pins -quiet $p]
    if {$ip eq ""} { puts $RES "  $p : (不存在)" }
    else {
        set net [get_bd_intf_nets -quiet -of_objects $ip]
        puts $RES "  $p : $net"
    }
}
set ic [get_bd_cells -quiet ps7_0_axi_periph]
if {$ic ne ""} {
    puts $RES "  ps7_0_axi_periph NUM_MI = [get_property CONFIG.NUM_MI $ic]"
}

# 地址
puts $RES ""
puts $RES "=== 地址分配 ==="
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_cells -quiet ps7_0_axi_periph]] {
    puts $RES "  $s"
}

# 时钟网络名 (集成时要用)
puts $RES ""
puts $RES "=== 全局时钟/复位网络 ==="
foreach n [get_bd_nets -quiet -filter {TYPE==clk}] { puts $RES "  CLK $n" }
foreach n [get_bd_nets -quiet -filter {TYPE==rst}] { puts $RES "  RST $n" }

# 校验
puts $RES ""
if {[catch {validate_bd_design} verr]} {
    puts $RES "VALIDATE=FAIL $verr"
} else {
    puts $RES "VALIDATE=OK  (BD 校验通过!)"
}
close $RES
puts ">>> 完成, 见 verify2018_result.txt"
exit 0
