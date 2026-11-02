#=====================================================================
#  addr2.tcl —— 正确分配 GPU 地址 + 核实原有外设地址
#=====================================================================
open_project {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.xpr}
open_bd_design [get_files system.bd]

set LOG [open "D:/ubuntu_iso/addr2_result.txt" w]

# ---- 先让 Vivado 自动分配没分配过的 ----
if {[catch {assign_bd_address} aerr]} {
    puts $LOG "assign_bd_address: $aerr"
}

# ---- GPU 从机段 -> 0x43CB0000 ----
set seg [get_bd_addr_segs -quiet {/gpu_0/s_axi/reg0}]
if {$seg eq ""} {
    puts $LOG "❌ 找不到 /gpu_0/s_axi/reg0"
    # 试试模糊匹配
    foreach s [get_bd_addr_segs] {
        if {[string match "*gpu_0*s_axi*" $s]} { puts $LOG "  候选: $s" }
    }
} else {
    set_property offset 0x43CB0000 $seg
    set_property range  64K        $seg
    puts $LOG "✅ GPU 控制寄存器地址 = 0x43CB0000 / 64K"
}

puts $LOG ""
puts $LOG "=== 全部地址映射 (段 -> offset) ==="
foreach s [lsort [get_bd_addr_segs]] {
    if {[catch {set o [get_property offset $s]} e]} { set o "?" }
    if {[catch {set r [get_property range $s]} e]} { set r "?" }
    puts $LOG "  [format %-58s $s] $o"
}

puts $LOG ""
puts $LOG "=== 关键外设地址核对 (应与原设备树一致) ==="
set want {
    "axi_gpio_0/S_AXI/Reg"           0x41200000
    "i2c2/S_AXI/Reg"                 0x41600000
    "lcd_out/lcd_pl_pwm/PWM_AXI"     0x43C00000
    "lcd_out/lcd_vtc/ctrl/Reg"       0x43C10000
    "lcd_out/v_frmbuf_rd_0/s_axi_CTRL/Reg" 0x43C20000
    "clk_wiz_0/s_axi_lite/Reg"       0x43C30000
    "audio/audio_formatter/s_axi_lite/reg0" 0x43C50000
}
foreach s [get_bd_addr_segs] {
    set o [get_property offset $s]
    set r [get_property range $s]
    if {$o ne "" && $o ne "0x00000000"} {
        puts $LOG "  [format %-58s $s] $o ($r)"
    } else {
        puts $LOG "  ⚠️ [format %-56s $s] offset 为空!"
    }
}

validate_bd_design
save_bd_design
puts $LOG ""
puts $LOG "✅ 已校验并保存"
close $LOG
puts ">>> 完成"
exit 0
