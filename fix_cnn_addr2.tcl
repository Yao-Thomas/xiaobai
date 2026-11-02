#=====================================================================
#  fix_cnn_addr2.tcl —— 给 CNN 的 6 条 m_axi 主控分配 DDR 地址段（修正版）
#
#  问题：
#    bd_cnn.tcl 只给从设备（s_axi_control）跑了 assign_bd_address，
#    **主控（m_axi）一个地址段都没分配**。
#    Zynq 的 AXI 主控必须显式分配地址段才能访问 DDR —— 不分配就是
#    "能收命令、搬不动数据"，表现正是：
#      · 寄存器写进去读得出 ✓
#      · 内核 ap_done 正常置位（2~3 ms）✓
#      · 但输出缓冲一个字节都没变 ✗
#
#  ★ 上一版脚本失败原因：地址空间名写错了。
#    主控的地址空间叫 `/cnn_conv_pool_0/Data_m_axi_gmem_img`
#    （Vivado 自动加了 "Data_" 前缀），不是 `/cnn_conv_pool_0/m_axi_gmem_img`。
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/fix_cnn_addr_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }
proc FAIL {msg} { global LOG; L "!! FAIL: $msg"; close $LOG; puts "RESULT=FAIL"; exit 1 }

L "======================================================"
L " 给 CNN m_axi 主控分配 DDR 地址段（v2）"
L " time: [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ
open_bd_design [get_files system.bd]
L "BD opened"

set SPACES {
    /cnn_conv_pool_0/Data_m_axi_gmem_img
    /cnn_conv_pool_0/Data_m_axi_gmem_w
    /cnn_conv_pool_0/Data_m_axi_gmem_out
    /cnn_fc_0/Data_m_axi_gmem_x
    /cnn_fc_0/Data_m_axi_gmem_w
    /cnn_fc_0/Data_m_axi_gmem_out
}

# ---------- 1. 现状 ----------
L ""
L ">>> 1. 修改前"
foreach spc $SPACES {
    if {[llength [get_bd_addr_spaces -quiet $spc]] == 0} {
        L "   [format %-44s %s]" $spc "!! 地址空间不存在"
        continue
    }
    set segs [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $spc]]
    L "   [format %-44s %s]" $spc "[llength $segs] 个段"
}

# ---------- 2. 找 DDR 段 ----------
L ""
L ">>> 2. 找可用的 DDR 地址段（走 HP3）"
set ddrseg ""
foreach s [get_bd_addr_segs -quiet] {
    if {[string match "*HP3*DDR*" $s]} {
        L "   候选: $s"
        if {$ddrseg eq ""} { set ddrseg $s }
    }
}
if {$ddrseg eq ""} {
    # 退一步：任何 DDR_LOWOCM 段
    foreach s [get_bd_addr_segs -quiet] {
        if {[string match "*DDR_LOWOCM*" $s]} { set ddrseg $s; break }
    }
}
if {$ddrseg eq ""} { FAIL "找不到 DDR 地址段" }
L "   选用: $ddrseg"

# ---------- 3. 分配 ----------
L ""
L ">>> 3. 逐个分配"
foreach spc $SPACES {
    if {[llength [get_bd_addr_spaces -quiet $spc]] == 0} { continue }
    set have [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $spc]]
    if {[llength $have] > 0} {
        L "   [format %-44s %s]" $spc "已有段，跳过"
        continue
    }
    if {[catch {
        assign_bd_address -force -target_address_space $spc $ddrseg
    } e]} {
        L "   !! 失败 $spc : $e"
    } else {
        L "   [format %-44s %s]" $spc "-> 已分配"
    }
}

# ---------- 4. 复查 ----------
L ""
L ">>> 4. 修改后"
set okcnt 0
foreach spc $SPACES {
    if {[llength [get_bd_addr_spaces -quiet $spc]] == 0} { continue }
    set segs [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $spc]]
    if {[llength $segs] > 0} { incr okcnt }
    L "   [format %-44s %s]" $spc "[llength $segs] 个段"
    foreach s $segs {
        set o "?"; catch { set o [get_property offset $s] }
        set r "?"; catch { set r [get_property range $s] }
        L "        $s = $o / $r"
    }
}
L ""
L "   合计: $okcnt / 6"
if {$okcnt < 6} { FAIL "还有 $((6-$okcnt)) 条主控没分到地址" }

# ---------- 5. 校验 / 保存 / 生成 ----------
L ""
L ">>> 5. validate"
if {[catch {validate_bd_design} e]} { FAIL "BD 校验失败: $e" }
L "   BD validated OK"

save_bd_design
L "   BD saved"

if {[catch {generate_target all [get_files system.bd]} e]} { FAIL "generate_target: $e" }
L "   targets generated"

L ""
L "======================================================"
L " 完成 —— 下一步要重新出 bitstream"
L "======================================================"
close $LOG
puts "RESULT=OK"
exit 0
