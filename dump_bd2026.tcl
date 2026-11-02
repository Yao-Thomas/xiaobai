# dump_bd2026.tcl —— 摸清升级后 BD 的结构, 为加 GPU 做准备
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/dump_bd2026.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

open_project $PROJ
open_bd_design [get_files system.bd]

L "=== 1. 顶层单元格 ==="
foreach c [lsort [get_bd_cells -quiet]] {
    set n [get_property NAME $c]
    set v "?"
    catch {set v [get_property VLNV $c]}
    L "  [format %-34s %$n] $v"
}

L ""
L "=== 2. PS7 的接口 (哪些 HP/GP 口被占了) ==="
foreach p [lsort [get_bd_intf_pins -quiet processing_system7_0/*]] {
    set n [get_property NAME $p]
    set nets [get_bd_intf_nets -quiet -of_objects $p]
    L "  [format %-46s %$n] -> $nets"
}

L ""
L "=== 3. ps7_0_axi_periph 的 NUM_MI / 连接 ==="
foreach prop {CONFIG.NUM_MI CONFIG.NUM_SI} {
    set v "?"
    catch {set v [get_property $prop [get_bd_cells ps7_0_axi_periph]]}
    L "  $prop = $v"
}
foreach p [lsort [get_bd_intf_pins -quiet ps7_0_axi_periph/*]] {
    set n [get_property NAME $p]
    set nets [get_bd_intf_nets -quiet -of_objects $p]
    L "  [format %-44s %$n] -> $nets"
}

L ""
L "=== 4. 时钟 / 复位网络 ==="
foreach n [lsort [get_bd_nets -quiet -filter {TYPE==clk}]] {
    L "  clk: $n"
}
foreach n [lsort [get_bd_nets -quiet -filter {TYPE==rst}]] {
    L "  rst: $n"
}

L ""
L "=== 5. 已有的从机地址映射 (确认哪些地址被占) ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    if {[string match "*Data*" $s] || [string match "*reg*" $s]} {
        set o "?"; set r "?"
        catch {set o [get_property offset $s]}
        catch {set r [get_property range $s]}
        if {$o ne "?" && $o ne "" && $o ne "0"} {
            L "  [format %-60s %$s] $o / $r"
        }
    }
}
L ""
L "DUMP-DONE"
close $LOG
exit 0
