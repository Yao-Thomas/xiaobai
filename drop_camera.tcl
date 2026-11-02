#=====================================================================
#  drop_camera.tcl —— 删掉 camera_in 子系统后重新出 bitstream
#  原因: v_frmbuf_wr:2.1 生成失败(2020.2 的 XCI 配置与 2.1 不兼容)
#        只有摄像头用 v_frmbuf_wr; LCD/HDMI 用 v_frmbuf_rd, 不受影响
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG [open "D:/ubuntu_iso/drop_camera_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "======================================================"
L " 去掉摄像头子系统 + 出 bitstream  [clock format [clock seconds]]"
L "======================================================"

open_project $PROJ
open_bd_design [get_files system.bd]

# ---- 删掉 camera_in ----
if {[llength [get_bd_cells -quiet camera_in]] > 0} {
    L " 删除 camera_in ..."
    delete_bd_objs [get_bd_cells camera_in]
    L " ✅ 已删除"
} else {
    L " camera_in 已不存在"
}

# 删除它残留的 IP 生成目录
foreach pat {*v_frmbuf_wr* *ov5640* *v_vid_in_axi4s*} {
    foreach d [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/ip/$pat] {
        L " 删除残留: [file tail $d]"
        file delete -force $d
    }
}

# ---- 重新生成 + 校验 ----
L ""
L ">>> 重新生成 IP  [clock format [clock seconds]]"
set BDOBJ [get_files system.bd]
reset_target all $BDOBJ
generate_target all $BDOBJ
L " ✅ 生成完成  [clock format [clock seconds]]"

if {[catch {validate_bd_design} verr]} {
    L " ❌ BD 校验失败: $verr"
    close $LOG
    exit 1
}
save_bd_design
L " ✅ BD 校验通过并保存"

set WFILE {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/hdl/system_wrapper.v}
if {![file exists $WFILE]} { catch {make_wrapper -files $BDOBJ -top} }
if {[file exists $WFILE] && [llength [get_files -quiet $WFILE]] == 0} {
    add_files -norecurse $WFILE
}
update_compile_order -fileset sources_1
set_property top system_wrapper [current_fileset]
L " top = [get_property top [current_fileset]]   源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"

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
            if {[string match "*ERROR*" $line] && $shown < 12} { L "   $line"; incr shown }
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
L " impl_1: [get_property PROGRESS [get_runs impl_1]]  [get_property STATUS [get_runs impl_1]]  [clock format [clock seconds]]"

L ""
L "=== 产物 ==="
foreach b [glob -nocomplain D:/ubuntu_iso/atk2018/atk2018.runs/impl_1/*.bit] {
    L "  ★ BIT: $b  ([file size $b] 字节)"
}
L " 结束: [clock format [clock seconds]]"
close $LOG
exit 0
