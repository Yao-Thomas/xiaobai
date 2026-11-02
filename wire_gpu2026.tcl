# wire_gpu2026.tcl —— 把 GPU 接进 BD (2026.1)
#  方案 (和 2018.3 时验证过的一样, 但这次是原生 IP):
#    · GPU 控制口  -> ps7_0_axi_periph M16 (NUM_MI 16->17)
#    · GPU 主机口  -> hp3_merge/S01 ; audio -> hp3_merge/S00 ; merge/M00 -> PS HP3
#    · 时钟/复位   -> FCLK_CLK0 + peripheral_aresetn
#    · ★ 关键: GPU 主机口的地址段必须是 0x00000000/1G (上次设成 64K 导致写显存被丢)
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/wire_gpu2026_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

open_project $PROJ
open_bd_design [get_files system.bd]

# 每次重跑先清理
if {[llength [get_bd_cells -quiet hp3_merge]] > 0} {
    L "清理: 删掉旧的 hp3_merge"
    catch {delete_bd_objs [get_bd_cells hp3_merge]}
}

L "=== 1. 先把 audio 的主口从 PS HP3 上摘下来 ==="
# 现在 PS 的 S_AXI_HP3 连的是 audio_M00_AXI, 先断开
set oldnet [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins processing_system7_0/S_AXI_HP3]]
L "  HP3 当前连的 net: $oldnet"
foreach n $oldnet {
    if {[catch {delete_bd_objs $n} e]} { L "  删 net 失败: $e" } else { L "  已删除 net: $n" }
}

L ""
L "=== 2. 建 hp3_merge (2 SI / 1 MI 互联) ==="
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 hp3_merge
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells hp3_merge]
L " ✅ hp3_merge 已建"

L ""
L "=== 3. 连线 ==="
# 主机口
connect_bd_intf_net [get_bd_intf_pins audio/M00_AXI]   [get_bd_intf_pins hp3_merge/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins gpu_0/m_axi]     [get_bd_intf_pins hp3_merge/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins hp3_merge/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP3]
L "  ✅ audio -> hp3_merge/S00"
L "  ✅ gpu   -> hp3_merge/S01"
L "  ✅ hp3_merge/M00 -> PS HP3"

# 控制口: NUM_MI 16 -> 17
set_property -dict [list CONFIG.NUM_MI {17}] [get_bd_cells ps7_0_axi_periph]
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M16_AXI] [get_bd_intf_pins gpu_0/s_axi]
L "  ✅ ps7_0_axi_periph/M16 -> gpu_0/s_axi (NUM_MI=17)"

L ""
L "=== 4. 时钟 / 复位 ==="
set CLK [get_bd_pins processing_system7_0/FCLK_CLK0]
set RST [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]
# GPU
connect_bd_net $CLK [get_bd_pins gpu_0/aclk]
connect_bd_net $RST [get_bd_pins gpu_0/aresetn]
# hp3_merge 的 5 个时钟 + 5 个复位
foreach p {ACLK S00_ACLK S01_ACLK M00_ACLK} {
    connect_bd_net $CLK [get_bd_pins hp3_merge/$p]
}
foreach p {ARESETN S00_ARESETN S01_ARESETN M00_ARESETN} {
    connect_bd_net $RST [get_bd_pins hp3_merge/$p]
}
# 新增的 M16 也要时钟复位
connect_bd_net $CLK [get_bd_pins ps7_0_axi_periph/M16_ACLK]
connect_bd_net $RST [get_bd_pins ps7_0_axi_periph/M16_ARESETN]
L "  ✅ 时钟复位全部接好"

L ""
L "=== 5. 分配地址 (必须用 assign_bd_address, set_property 会因为只读而失败) ==="
# 先看有哪些段
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*gpu_0*" $s]} { L "  GPU 段: $s" }
}

# --- 从机: GPU 控制寄存器 0x43CB0000 / 64K ---
set sseg ""
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*gpu_0/s_axi*" $s]} { set sseg $s }
}
if {$sseg ne ""} {
    if {[catch {
        assign_bd_address -force -offset 0x43CB0000 -range 64K \
            -target_address_space /processing_system7_0/Data $sseg
    } e3]} {
        L "  ❌ 从机地址分配失败: $e3"
    } else {
        L "  ✅ 从机 $sseg -> 0x43CB0000 / 64K"
    }
} else { L "  ⚠️ 没找到 gpu_0 的从机段" }

# --- ★ 主机: 必须是 1G (上次设成 64K 导致写显存全被互联丢弃) ---
set mseg ""
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*gpu_0/m_axi*" $s]} { set mseg $s }
}
if {$mseg ne ""} {
    # 先看修改前
    set o0 "?"; set r0 "?"
    catch {set o0 [get_property offset $mseg]}
    catch {set r0 [get_property range  $mseg]}
    L "  主机段修改前: offset=$o0 range=$r0"
    if {[catch {
        assign_bd_address -force -offset 0x00000000 -range 1G \
            -target_address_space /gpu_0/m_axi \
            [get_bd_addr_segs processing_system7_0/S_AXI_HP3/HP3_DDR_LOWOCM]
    } e4]} {
        L "  ❌ 主机段分配失败: $e4"
    }
    set o1 "?"; set r1 "?"
    catch {set o1 [get_property offset $mseg]}
    catch {set r1 [get_property range  $mseg]}
    L "  主机段修改后: offset=$o1 range=$r1"
    if {$r1 eq "0x40000000" || $r1 eq "1G" || $r1 eq "1073741824"} {
        L "  ✅ 主机段 = 1G  ★关键修复到位"
    } else {
        L "  ⚠️ 主机段不是 1G, 需要再处理"
    }
} else { L "  ⚠️ 没找到 gpu_0 的主机段" }

L ""
L "=== 6. 校验 + 保存 ==="
if {[catch {validate_bd_design} e2]} {
    L " ❌ BD 校验失败: $e2"
    close $LOG
    exit 1
}
L " ✅ BD 校验通过"
L "  实例数: [llength [get_bd_cells -quiet]]"
save_bd_design
L " ✅ 已保存"
L ""
L "=== 最终检查: GPU 地址 ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    set o "?"
    catch {set o [get_property offset $s]}
    if {$o eq "0x43CB0000" || [string match "*gpu_0/m_axi*" $s]} {
        set r "?"; catch {set r [get_property range $s]}
        L "  $s  =  $o / $r"
    }
}
L "=== 结束 ==="
close $LOG
exit 0
