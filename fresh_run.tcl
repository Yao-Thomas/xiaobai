#=====================================================================
#  fresh_run.tcl —— 删除旧 run, 重建后再出 bitstream
#  旧 run 的 system_wrapper.tcl 是 IP 还坏着的时候生成的, 引用失效
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG  [open "D:/ubuntu_iso/fresh_run_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 重建 run + 出 bitstream  [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ

# ---- 删掉所有 run ----
foreach r [get_runs -quiet] {
    L " 删除 run: $r"
    catch {delete_runs $r -force}
}
# 清掉 runs 目录残留
file delete -force D:/ubuntu_iso/atk2018/atk2018.runs

# ---- 确保 BD 和 wrapper 状态正确 ----
open_bd_design [get_files system.bd]
set BDOBJ [get_files system.bd]
generate_target all $BDOBJ
validate_bd_design
save_bd_design
L " ✅ BD 已重新生成并校验"

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {![file exists $WFILE]} { catch {make_wrapper -files $BDOBJ -top} }
if {[file exists $WFILE] && [llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " 源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"

# ---- 新建 run ----
L ""
L ">>> 新建 synth_1 / impl_1  [clock format [clock seconds]]"
create_run synth_1 -flow "Vivado Synthesis 2018" \
    -strategy "Vivado Synthesis Defaults" \
    -constrs [get_filesets constrs_1]
create_run impl_1 -flow "Vivado Implementation 2018" \
    -strategy "Vivado Implementation Defaults" \
    -constrs [get_filesets constrs_1] -parent_run synth_1
L " ✅ run 已创建"

# ---- 综合 ----
L ""
L ">>> 综合 synth_1  [clock format [clock seconds]]"
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
            if {([string match "*ERROR*" $line] || [string match "*bad lexical*" $line] || [string match "*No files matched*" $line]) && $shown < 12} {
                L "   $line"; incr shown
            }
        }
    }
    close $LOG
    exit 1
}
L " ✅✅✅ 综合通过!"

# ---- 实现 ----
L ""
L ">>> 实现 impl_1  [clock format [clock seconds]]"
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]  [clock format [clock seconds]]"

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit] {
    L "  ★★★ BIT: $b  ([file size $b] 字节)"
}
L " 结束: [clock format [clock seconds]]"
close $LOG
exit 0
