#=====================================================================
#  integrate_gpu_2018.tcl —— 用 Vivado 2018.3 把自研 GPU 集成进正点原子设计
#---------------------------------------------------------------------
#  前提: BD 里 3 个 Xilinx IP 版本已替换 (v_tc:6.1 / v_frmbuf_*:2.1)
#  用法: vivado -mode batch -source integrate_gpu_2018.tcl
#=====================================================================
set ATK     {D:/ubuntu_iso/tmp_try2018/Navigator_7020}
set BD      $ATK/Navigator_7020.srcs/sources_1/bd/system/system.bd
set XDC     $ATK/Navigator_7020.srcs/constrs_1/system.xdc
set ATKREPO $ATK/ip_repo
set GPUREPO {D:/ubuntu_iso/gpu_ip}
set PROJ    {D:/ubuntu_iso/tmp_try2018/gpu_proj}
set GPUADDR 0x43CB0000

set LOG [open "D:/ubuntu_iso/integrate_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; puts $msg }

L "======================================================"
L " GPU 集成 (Vivado [version -short])"
L "======================================================"

# ---------- 1. 建工程 ----------
if {[file exists $PROJ]} { file delete -force $PROJ }
create_project -force gpu_proj $PROJ -part xc7z020clg400-2
L " ✅ 工程已建: $PROJ"

set_property ip_repo_paths [list $ATKREPO $GPUREPO] [current_project]
update_ip_catalog -rebuild
L " ✅ IP 目录已更新 (正点原子 9 个 + 自研 GPU)"

set gpuips [get_ipdefs -all *dsh*gpu2d*]
if {[llength $gpuips] == 0} { L " ❌ 找不到自研 GPU IP!"; close $LOG; exit 1 }
L " ✅ 找到自研 IP: $gpuips"

# ---------- 2. 导入 BD + 约束 ----------
add_files -norecurse $BD
add_files -fileset constrs_1 -norecurse $XDC
update_compile_order -fileset sources_1
L " ✅ BD + 约束已加入"

# ---------- 3. 打开 BD ----------
if {[catch {open_bd_design [get_files system.bd]} err]} {
    L " ❌ BD 打开失败: $err"; close $LOG; exit 1
}
L " ✅ BD 已打开"

# ---------- 4. 添加 GPU ----------
if {[llength [get_bd_cells -quiet gpu_0]] > 0} {
    delete_bd_objs [get_bd_cells gpu_0]
}
create_bd_cell -type ip -vlnv dsh:user:gpu2d_axi:1.0 gpu_0
L " ✅ 已添加 gpu_0"

# ---------- 5. 控制口: NUM_MI 16 -> 17 ----------
set nummi [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
L " 当前 NUM_MI = $nummi"
if {$nummi < 17} {
    set_property -dict [list CONFIG.NUM_MI {17}] [get_bd_cells ps7_0_axi_periph]
    L " ✅ NUM_MI -> 17"
}
set m16 [get_bd_intf_pins -quiet ps7_0_axi_periph/M16_AXI]
if {$m16 eq ""} { L " ❌ 没有 M16_AXI"; close $LOG; exit 1 }
connect_bd_intf_net $m16 [get_bd_intf_pins gpu_0/S_AXI]
L " ✅ 控制口 -> ps7_0_axi_periph/M16_AXI"

# ---------- 6. 主机口: 与 audio 共用 HP3 ----------
if {[llength [get_bd_cells -quiet hp3_merge]] > 0} {
    delete_bd_objs [get_bd_cells hp3_merge]
}
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 hp3_merge
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells hp3_merge]
L " ✅ 已建 hp3_merge (2 从 1 主)"

set oldnet [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins processing_system7_0/S_AXI_HP3]]
if {$oldnet ne ""} {
    L " 拆掉原连接: $oldnet"
    delete_bd_objs $oldnet
} else {
    L " ⚠️ 没找到原来连 HP3 的线(可能名字不同)"
}
connect_bd_intf_net [get_bd_intf_pins audio/M00_AXI]     [get_bd_intf_pins hp3_merge/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins gpu_0/M_AXI]       [get_bd_intf_pins hp3_merge/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins hp3_merge/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP3]
L " ✅ 主机口 -> 与 audio 共用 S_AXI_HP3"

# ---------- 7. 时钟/复位 ----------
#  ★ 要连的是【源引脚】, 不是网络名
set iclk   [get_bd_pins -quiet ps7_0_axi_periph/ACLK]
set ireset [get_bd_pins -quiet ps7_0_axi_periph/ARESETN]
set clk_net [get_bd_nets -quiet -of_objects $iclk]
set rst_net [get_bd_nets -quiet -of_objects $ireset]
L " 时钟网络: $clk_net   复位网络: $rst_net"

set clk_src [get_bd_pins -quiet -of_objects $clk_net -filter {TYPE==clk}]
set rst_src [get_bd_pins -quiet -of_objects $rst_net -filter {TYPE==rst}]
L " 时钟源引脚: $clk_src"
L " 复位源引脚: $rst_src"

if {[llength $clk_src] == 0 || [llength $rst_src] == 0} {
    L " ❌ 找不到时钟/复位源引脚"; close $LOG; exit 1
}

connect_bd_net [lindex $clk_src 0] \
    [get_bd_pins gpu_0/aclk] \
    [get_bd_pins hp3_merge/ACLK] \
    [get_bd_pins hp3_merge/S00_ACLK] \
    [get_bd_pins hp3_merge/S01_ACLK] \
    [get_bd_pins hp3_merge/M00_ACLK] \
    [get_bd_pins -quiet ps7_0_axi_periph/M16_ACLK]
connect_bd_net [lindex $rst_src 0] \
    [get_bd_pins gpu_0/aresetn] \
    [get_bd_pins hp3_merge/ARESETN] \
    [get_bd_pins hp3_merge/S00_ARESETN] \
    [get_bd_pins hp3_merge/S01_ARESETN] \
    [get_bd_pins hp3_merge/M00_ARESETN] \
    [get_bd_pins -quiet ps7_0_axi_periph/M16_ARESETN]
L " ✅ 时钟/复位已接 (含互联新增的 M16_ACLK)"

# ---- 诊断: 列出所有没接的时钟/复位引脚 ----
L ""
L "=== 全 BD 未连接的时钟/复位引脚 ==="
set nbad 0
foreach p [get_bd_pins -quiet -filter {TYPE==clk || TYPE==rst}] {
    set n [get_bd_nets -quiet -of_objects $p]
    if {$n eq ""} { L "  ✗ $p"; incr nbad }
}
L "  合计: $nbad 个"

L ""
L "=== gpu_0 的引脚连接 ==="
foreach p [get_bd_pins -quiet gpu_0/*] {
    L "  [get_property PATH $p] -> [get_bd_nets -quiet -of_objects $p]"
}
L ""
L "=== hp3_merge 的时钟/复位 ==="
foreach p [get_bd_pins -quiet hp3_merge/*] {
    set t [get_property TYPE $p]
    if {$t eq "clk" || $t eq "rst"} {
        L "  [get_property PATH $p] -> [get_bd_nets -quiet -of_objects $p]"
    }
}

# ---------- 8. 地址 ----------
assign_bd_address -quiet
set seg [get_bd_addr_segs -quiet gpu_0/S_AXI/Reg]
if {$seg ne ""} {
    set_property offset $GPUADDR $seg
    set_property range  64K      $seg
    L " ✅ GPU 地址 = $GPUADDR / 64K"
} else {
    L " ⚠️ 找不到 gpu_0/S_AXI/Reg"
}

# ---------- 9. 校验 ----------
if {[catch {validate_bd_design} verr]} {
    L " ❌ BD 校验失败:"; L "    $verr"; close $LOG; exit 1
}
save_bd_design
L " ✅ BD 校验通过并已保存"

# 关键信息
L ""
L "=== 结果摘要 ==="
set seg2 [get_bd_addr_segs -quiet gpu_0/S_AXI/Reg]
if {$seg2 ne ""} {
    L "  GPU 地址: [get_property offset $seg2]  范围: [get_property range $seg2]"
}
L "  BD 实例数: [llength [get_bd_cells]]"
L "  NUM_MI: [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]"

close $LOG
L ">>> 集成完成 ✅  (详见 integrate_result.txt)"
exit 0
