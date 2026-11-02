# fix_mseg2026.tcl —— 无条件给 GPU 主机口分配 1G 地址段
#  根因: GPU 的 m_axi 地址空间里一个段都没有 -> 写显存会被互联丢弃
#  (上次在 2018.3 上就是这个问题: 段被误设成 64K)
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/fix_mseg2026_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

open_project $PROJ
open_bd_design [get_files system.bd]

L "=== 修改前: 所有地址段 ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    set o "?"; set r "?"
    catch {set o [get_property offset $s]}
    catch {set r [get_property range $s]}
    L "  [format %-62s %$s] $o / $r"
}

L ""
L "=== 给 GPU 主机口分配 0x00000000 / 1G ==="
set blk [get_bd_addr_segs -quiet processing_system7_0/S_AXI_HP3/HP3_DDR_LOWOCM]
L "  目标地址块: $blk"
if {[llength $blk] == 0} {
    L " ❌ 找不到 HP3 的 DDR 地址块!"
    close $LOG
    exit 1
}
if {[catch {
    assign_bd_address -force -offset 0x00000000 -range 1G \
        -target_address_space /gpu_0/m_axi $blk
} e]} {
    L " ❌ 失败: $e"
} else {
    L " ✅ assign_bd_address 成功"
}

L ""
L "=== 修改后: GPU 相关的段 ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    if {[string match "*gpu_0*" $s]} {
        set o "?"; set r "?"
        catch {set o [get_property offset $s]}
        catch {set r [get_property range $s]}
        L "  [format %-62s %$s] $o / $r"
    }
}

L ""
L "=== 校验 + 保存 ==="
if {[catch {validate_bd_design} e2]} {
    L " ❌ 校验失败: $e2"
    close $LOG
    exit 1
}
L " ✅ 校验通过"
save_bd_design
L " ✅ 已保存"
L "=== 结束 ==="
close $LOG
exit 0
