# upgrade2026.tcl —— 用 Vivado 2026.1 打开正点原子工程并升级
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/upgrade2026_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 用 Vivado 2026.1 升级正点原子工程 ==="
L " Vivado: [version -short]"
L " 时间: [clock format [clock seconds]]"
L ""
L ">>> 打开工程"
if {[catch {open_project $PROJ} e]} {
    L " ❌ 打开失败: $e"
    close $LOG
    exit 1
}
L " ✅ 工程已打开"

# ---- 列出所有 IP 及版本 ----
L ""
L "=== 工程里的 IP ==="
set ips [get_ips -quiet]
L " IP 总数: [llength $ips]"
foreach ip [lsort $ips] {
    set d "?"
    catch {set d [get_property IPDEF $ip]}
    L "   [format %-28s $ip] $d"
}

# ---- 检查 BD ----
L ""
L "=== Block Design ==="
set bds [get_files -quiet *.bd]
L " BD 数: [llength $bds]"
foreach b $bds { L "   $b" }

# ---- 升级 IP ----
L ""
L ">>> 升级 IP 到 2026.1 的版本"
set nfail 0
foreach ip $ips {
    if {[catch {upgrade_ip -quiet $ip} e2]} {
        L "  ❌ $ip : $e2"
        incr nfail
    } else {
        L "  ✅ $ip 已升级"
    }
}
L " 失败数: $nfail"

# ---- 打开 BD 看看能不能认 ----
L ""
L ">>> 打开 system.bd"
set bd [get_files -quiet system.bd]
if {[llength $bd] > 0} {
    if {[catch {open_bd_design $bd} e3]} {
        L " ❌ BD 打开失败: $e3"
    } else {
        L " ✅ BD 打开成功"
        if {[catch {validate_bd_design} e4]} {
            L " ❌ BD 校验失败: $e4"
        } else {
            L " ✅ BD 校验通过"
        }
        L " 实例数: [llength [get_bd_cells -quiet]]"
        # 列出视频相关的实例
        foreach c [lsort [get_bd_cells -quiet]] {
            set n [get_property NAME $c]
            if {[string match "*frmbuf*" $n] || [string match "*vtc*" $n] || \
                [string match "*lcd*" $n] || [string match "*hdmi*" $n] || \
                [string match "*disp*" $n]} {
                set v "?"
                catch {set v [get_property VLNV $c]}
                L "   $n  ->  $v"
            }
        }
        save_bd_design
        L " ✅ BD 已保存"
    }
} else { L " ⚠️ 没找到 system.bd" }

L ""
L ">>> 保存工程"
catch {save_project}
L " ✅ 已保存"
L ""
L "=== 结束 [clock format [clock seconds]] ==="
close $LOG
exit 0
