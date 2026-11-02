#=====================================================================
#  upgrade2018.tcl —— 关键: 改 IP 版本后必须 upgrade_ip 迁移配置
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG [open "D:/ubuntu_iso/upgrade_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " upgrade_ip 迁移 IP 配置 + 出 bitstream  [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ
open_bd_design [get_files system.bd]

# ---- 看哪些 IP 需要升级 ----
L ""
L "=== 需要升级的 IP ==="
set need [get_ips -quiet]
if {[catch {set need [get_ips -quiet -filter {IS_UPGRADE_NEEDED==1}]} e]} {
    L "  (查询失败: $e), 改用全量升级"
}
L "  数量: [llength $need]"
foreach ip $need { L "   - [get_property NAME $ip]  ([get_property VLNV $ip])" }

# ---- 升级 ----
L ""
L ">>> upgrade_ip  [clock format [clock seconds]]"
if {[catch {upgrade_ip [get_ips]} uerr]} {
    L " ⚠️ upgrade_ip: $uerr"
} else {
    L " ✅ upgrade_ip 完成"
}
if {[catch {upgrade_ip [get_ips -quiet -filter {IS_UPGRADE_NEEDED==1}]} uerr2]} {
    # 忽略: 已经没有需要升级的了
}

# ---- 重新生成 ----
L ""
L ">>> generate_target all  [clock format [clock seconds]]"
set BDOBJ [get_files system.bd]
reset_target all $BDOBJ
generate_target all $BDOBJ
L " ✅ 生成完成  [clock format [clock seconds]]"

validate_bd_design
save_bd_design
L " ✅ BD 校验通过"

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {![file exists $WFILE]} { catch {make_wrapper -files $BDOBJ -top} }
if {[file exists $WFILE] && [llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " 源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"

# ---- 综合 ----
L ""
L ">>> 综合 synth_1  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st  [clock format [clock seconds]]"

if {![string match "*Complete*" $st]} {
    L " ❌ 综合失败:"
    set vds {D:/ubuntu_iso/atk2018/atk2018.runs/synth_1/system_wrapper.vds}
    if {[file exists $vds]} {
        set f [open $vds r]; set t [read $f]; close $f
        set shown 0
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] && $shown < 10} { L "   $line"; incr shown }
        }
    }
    # 找 IP 生成的错误
    L " --- IP 生成错误 ---"
    foreach rl [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/*/runme.log] {
        set f [open $rl r]; set t [read $f]; close $f
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line]} { L "   [[file tail [file dirname $rl]]] $line" }
        }
    }
    close $LOG
    exit 1
}
L " ✅ 综合通过!"

# ---- 实现 ----
L ""
L ">>> 实现 impl_1  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]"

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit] {
    L "  ★ BIT: $b  ([file size $b] 字节)"
}
L " 结束: [clock format [clock seconds]]"
close $LOG
exit 0
