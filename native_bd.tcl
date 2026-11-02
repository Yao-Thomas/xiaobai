#=====================================================================
#  native_bd.tcl —— 把 BD 变成"工程原生", 再出 bitstream
#  关键: BD 必须位于 <proj>/<proj>.srcs/sources_1/bd/system/
#        否则 Vivado 不把它当 IP Integrator 源, 生成的 IP 文件不会进编译列表
#=====================================================================
set ATK  {D:/ubuntu_iso/tmp_try2018/Navigator_7020}
set NEW  {D:/ubuntu_iso/atk2018}
set LOG  [open "D:/ubuntu_iso/native_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 原生 BD 方案  [clock format [clock seconds]]"
L "======================================================"

# ---- 1. 建工程 ----
if {[file exists $NEW]} { file delete -force $NEW }
create_project -force atk2018 $NEW -part xc7z020clg400-2
L " ✅ 工程: $NEW"

set_property ip_repo_paths [list $ATK/ip_repo {D:/ubuntu_iso/gpu_ip}] [current_project]
update_ip_catalog -rebuild
L " ✅ IP 目录已更新"

# ---- 2. 把 BD 目录整个复制到工程原生位置 ----
set dstbd $NEW/atk2018.srcs/sources_1/bd/system
file mkdir $dstbd
foreach item [glob -nocomplain $ATK/Navigator_7020.srcs/sources_1/bd/system/*] {
    set nm [file tail $item]
    if {$nm eq "system.bd.orig"} { continue }
    file copy -force $item $dstbd/$nm
    L "  复制: $nm"
}
set BDFILE $dstbd/system.bd
if {![file exists $BDFILE]} { L " ❌ BD 复制失败"; close $LOG; exit 1 }
L " ✅ BD 已复制到工程原生位置"

# ---- 3. 加入工程 ----
add_files -norecurse $BDFILE
add_files -fileset constrs_1 -norecurse $ATK/Navigator_7020.srcs/constrs_1/system.xdc
update_compile_order -fileset sources_1
L " ✅ BD + 约束已加入"

open_bd_design $BDFILE
L " ✅ BD 已打开"

# ---- 4. 生成 + wrapper ----
L ""
L ">>> generate_target all  [clock format [clock seconds]]"
set BDOBJ [get_files system.bd]
if {$BDOBJ eq ""} { L " ❌ get_files system.bd 返回空"; close $LOG; exit 1 }
L " BD 对象: $BDOBJ"
reset_target all $BDOBJ
generate_target all $BDOBJ
L " ✅ 生成完成  [clock format [clock seconds]]"

set WFILE $dstbd/hdl/system_wrapper.v
if {![file exists $WFILE]} {
    L " 生成 wrapper ..."
    catch {make_wrapper -files $BDFILE -top}
}
if {![file exists $WFILE]} {
    # 有时生成到 .gen 下
    set cand [glob -nocomplain $NEW/atk2018.gen/sources_1/bd/system/hdl/*wrapper*]
    if {[llength $cand] > 0} { set WFILE [lindex $cand 0] }
}
L " wrapper: $WFILE  ([expr {[file exists $WFILE] ? [file size $WFILE] : 0}] 字节)"
if {![file exists $WFILE]} { L " ❌ wrapper 没生成"; close $LOG; exit 1 }
if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }

update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " top = [get_property top [current_fileset]]"
L " 源文件数: [llength [get_files -of_objects [get_filesets sources_1]]]"

# ---- 5. 综合 ----
L ""
L ">>> 综合 synth_1  [clock format [clock seconds]]"
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st  [clock format [clock seconds]]"

if {![string match "*Complete*" $st]} {
    L " ❌ 综合失败, 错误:"
    set vds $NEW/atk2018.runs/synth_1/system_wrapper.vds
    if {[file exists $vds]} {
        set f [open $vds r]; set t [read $f]; close $f
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line]} { L "   $line" }
        }
    }
    close $LOG
    exit 1
}

# ---- 6. 实现 ----
L ""
L ">>> 实现 impl_1  [clock format [clock seconds]]"
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]  [clock format [clock seconds]]"

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain $NEW/atk2018.runs/impl_1/*.bit] {
    L "  BIT: $b  ([file size $b] 字节)"
}
close $LOG
exit 0
