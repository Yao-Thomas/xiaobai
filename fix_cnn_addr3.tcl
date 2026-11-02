#=====================================================================
#  fix_cnn_addr3.tcl —— 给 CNN 的 6 条 m_axi 主控分配 DDR 地址段
#
#  问题：bd_cnn.tcl 只给从设备(s_axi_control)分配了地址，
#        6 条 m_axi 主控**一个地址段都没有**。
#        Zynq AXI 主控必须显式分地址段才能访问 DDR，否则就是
#        "能收命令、搬不动数据"：
#          · 寄存器读写正常 ✓
#          · ap_done 正常置位（2~3 ms）✓
#          · 输出缓冲一个字节都不变 ✗
#
#  ★ 两个坑（前两版脚本踩的）：
#     1) 主控的地址空间名有 "Data_" 前缀：
#        /cnn_conv_pool_0/Data_m_axi_gmem_img
#     2) Tcl 的 proc 只收一个参数时，不能传多个 —— L 改成 varargs
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/fix_cnn_addr_result.txt" w]

proc L {args} {
    global LOG
    set msg [join $args " "]
    puts $LOG $msg
    flush $LOG
    puts $msg
}
proc FAIL {args} {
    global LOG
    L "!! FAIL:" {*}$args
    close $LOG
    puts "RESULT=FAIL"
    exit 1
}

L "======================================================"
L " 给 CNN m_axi 主控分配 DDR 地址段 (v3)"
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
        L "   $spc  !! 地址空间不存在"
        continue
    }
    set segs [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $spc]]
    L "   $spc  ->  [llength $segs] 个段"
}

# ---------- 2. 找 DDR 段 ----------
L ""
L ">>> 2. 找 DDR 地址段"
#
# ★ 关键：必须用【从设备侧】的那个段
#     /processing_system7_0/S_AXI_HP3/HP3_DDR_LOWOCM
#   而不是别的 master 地址空间里的同名段（比如
#     /audio/audio_formatter/m_axi_mm2s/SEG_..._HP3_DDR_LOWOCM
#   那个是 audio 自己的映射，拿来给 CNN 分配只会"看起来成功、
#   实际分了个不属于它的段"，复查时仍然 0 个段）。
#
set ddrseg "/processing_system7_0/S_AXI_HP3/HP3_DDR_LOWOCM"
if {[llength [get_bd_addr_segs -quiet $ddrseg]] == 0} {
    L "   指定的段不存在，退回去搜从设备侧的段"
    set ddrseg ""
    foreach s [get_bd_addr_segs -quiet] {
        if {[string match "/processing_system7_0/S_AXI_HP*/*DDR*" $s]} {
            L "   候选: $s"
            if {$ddrseg eq ""} { set ddrseg $s }
        }
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
        L "   $spc  已有段，跳过"
        continue
    }
    if {[catch {
        # ★ 必须传 get_bd_addr_segs 返回的**对象**，不能传路径字符串
        #   （传字符串会报 Common 17-161 Invalid option value）
        assign_bd_address -force \
            -target_address_space [get_bd_addr_spaces $spc] \
            [get_bd_addr_segs $ddrseg]
    } e]} {
        L "   !! 失败 $spc : $e"
    } else {
        L "   $spc  -> 已分配"
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
    L "   $spc  ->  [llength $segs] 个段"
    foreach s $segs {
        set o "?"
        catch { set o [get_property offset $s] }
        set r "?"
        catch { set r [get_property range $s] }
        L "        $s = $o / $r"
    }
}
L ""
L "   合计: $okcnt / 6"
if {$okcnt < 6} { FAIL "还有主控没分到地址 ($okcnt/6)" }

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
L " 完成 —— 需要重新出 bitstream"
L "======================================================"
close $LOG
puts "RESULT=OK"
exit 0
