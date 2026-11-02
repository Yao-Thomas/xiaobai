# add_gpu2026.tcl —— 把自研 GPU IP 加进 2026.1 工程的 BD, 并列出它的引脚
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/add_gpu2026_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 把 GPU 加进 2026.1 工程 ==="
L " 时间: [clock format [clock seconds]]"
open_project $PROJ

# ---- 1. 加 IP 仓库 ----
L ""
L ">>> 加 IP 仓库 D:/ubuntu_iso/gpu_ip"
set cur [get_property ip_repo_paths [current_project]]
L "  原有: $cur"
set_property ip_repo_paths [concat $cur {D:/ubuntu_iso/gpu_ip}] [current_project]
update_ip_catalog -rebuild
L " ✅ 目录已更新"

# 确认能认到
L "  查找 gpu2d_axi:"
set found 0
foreach d [get_ipdefs -quiet *gpu2d*] { L "     $d"; incr found }
if {$found == 0} { L "  ❌ 没认到 gpu2d_axi !" }

# ---- 2. 打开 BD 加 cell ----
L ""
L ">>> 打开 system.bd 并加 gpu_0"
open_bd_design [get_files system.bd]

# 已经加过就先删掉 (方便重跑)
if {[llength [get_bd_cells -quiet gpu_0]] > 0} {
    L "  (gpu_0 已存在, 先删掉重加)"
    delete_bd_objs [get_bd_cells gpu_0]
}

if {[catch {
    create_bd_cell -type ip -vlnv dsh:user:gpu2d_axi:1.0 gpu_0
} e1]} {
    L " ❌ 创建失败: $e1"
    L " 试试列一下所有 user IP:"
    foreach d [get_ipdefs -quiet *user*] { L "   $d" }
    close $LOG
    exit 1
}
L " ✅ gpu_0 已创建"

# ---- 3. 列出 gpu_0 的所有引脚 ----
L ""
L "=== gpu_0 的接口引脚 (intf) ==="
foreach p [lsort [get_bd_intf_pins -quiet gpu_0/*]] {
    set mode "?"
    catch {set mode [get_property MODE $p]}
    L "  [format %-30s %$p] mode=$mode"
}
L ""
L "=== gpu_0 的普通引脚 (pin) ==="
foreach p [lsort [get_bd_pins -quiet gpu_0/*]] {
    set d "?"
    catch {set d [get_property DIR $p]}
    L "  [format %-30s %$p] $d"
}

L ""
L "=== 顺便列出 hp3_merge 是否已存在 / audio 的主口 ==="
L "  hp3_merge: [get_bd_cells -quiet hp3_merge]"
foreach p [get_bd_intf_pins -quiet audio/*] {
    set mode "?"
    catch {set mode [get_property MODE $p]}
    if {$mode eq "Master"} { L "  audio 主口: $p" }
}
L ""
L "=== 参考: 现有互联的时钟/复位引脚名 ==="
foreach pat {ps7_0_axi_periph/M00_ACLK ps7_0_axi_periph/M00_ARESETN processing_system7_0/FCLK_CLK0 rst_ps7_0_100M/peripheral_aresetn} {
    set p [get_bd_pins -quiet $pat]
    L "  [format %-52s %$pat] -> $p"
}

L ""
L ">>> 保存"
save_bd_design
L " ✅ 已保存"
L "=== 结束 ==="
close $LOG
exit 0
