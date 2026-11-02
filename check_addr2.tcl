#=====================================================================
#  check_addr2.tcl —— 查 GPU 主机口的地址段 + 接口位宽
#=====================================================================
open_project {D:/ubuntu_iso/atk2018/atk2018.xpr}
open_bd_design [get_files system.bd]

set LOG [open "D:/ubuntu_iso/check_addr2_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 1. gpu_0 的主机地址空间及其段 ==="
foreach as [get_bd_addr_spaces -quiet -of_objects [get_bd_cells gpu_0]] {
    L "  地址空间: $as"
    foreach s [get_bd_addr_segs -quiet -of_objects $as] {
        set o "?"; set r "?"
        catch {set o [get_property offset $s]}
        catch {set r [get_property range $s]}
        L "     ★ $s"
        L "        offset=$o  range=$r"
    }
}

L ""
L "=== 2. hp3_merge 的从口地址段 ==="
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_cells hp3_merge]] {
    set o "?"; set r "?"
    catch {set o [get_property offset $s]}
    catch {set r [get_property range $s]}
    L "  $s  offset=$o range=$r"
}

L ""
L "=== 3. 接口位宽 (关键: GPU 32bit vs HP 口可能 64bit) ==="
foreach p {gpu_0/M_AXI gpu_0/S_AXI hp3_merge/S00_AXI hp3_merge/S01_AXI
           hp3_merge/M00_AXI processing_system7_0/S_AXI_HP3} {
    set ip [get_bd_intf_pins -quiet $p]
    if {$ip eq ""} { L "  $p : 不存在"; continue }
    set w "?"
    catch {set w [get_property CONFIG.DATA_WIDTH $ip]}
    set n [get_bd_intf_nets -quiet -of_objects $ip]
    L "  [format %-34s $p] width=$w  net=$n"
}

L ""
L "=== 4. 自动插入的转换器 (auto_ds/auto_us) ==="
foreach c [get_bd_cells -quiet] {
    set n [get_property NAME $c]
    if {[string match "auto_*" $n] || [string match "*dwidth*" $n]} {
        set v "?"
        catch {set v [get_property VLNV $c]}
        L "  $n   ($v)"
    }
}
close $LOG
puts ">>> 完成"
exit 0
