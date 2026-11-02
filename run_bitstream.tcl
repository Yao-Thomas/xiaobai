#=====================================================================
#  run_bitstream.tcl —— IP 已生成好, 直接综合 + 实现 + 出流
#=====================================================================
set LOG [open "D:/ubuntu_iso/run_bit_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 出 bitstream  [clock format [clock seconds]]"
L "======================================================"

open_project {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.xpr}

set WFILE {D:/ubuntu_iso/tmp_try2018/Navigator_7020/Navigator_7020.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {[llength [get_files -quiet $WFILE]] == 0} { add_files -norecurse $WFILE }
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " top = [get_property top [current_fileset]]"
L " 源文件数: [llength [get_files -of_objects [get_filesets sources_1]]]"

# ---- 综合 ----
L ""
L ">>> 综合 synth_1  [clock format [clock seconds]]"
reset_run synth_1 -quiet
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set st [get_property STATUS [get_runs synth_1]]
L " synth_1: [get_property PROGRESS [get_runs synth_1]]  $st  [clock format [clock seconds]]"

if {![string match "*Complete*" $st]} {
    L " ❌ 综合失败"
    # 从 vds 日志找错误
    set vds {D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/synth_1/system_wrapper.vds}
    if {[file exists $vds]} {
        set f [open $vds r]; set t [read $f]; close $f
        L " --- system_wrapper.vds 里的 ERROR ---"
        foreach line [split $t "\n"] {
            if {[string match "*ERROR*" $line] || [string match "*No files matched*" $line]} {
                L "   $line"
            }
        }
    }
    close $LOG
    exit 1
}

# ---- 实现 ----
L ""
L ">>> 实现 impl_1  [clock format [clock seconds]]"
reset_run impl_1 -quiet
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]  [clock format [clock seconds]]"

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/tmp_try2018/gpu_proj/gpu_proj.runs/impl_1/*.bit] {
    L "  BIT: $b  ([file size $b] 字节)"
}
close $LOG
exit 0
