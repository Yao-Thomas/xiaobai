#=====================================================================
#  regen_gpu.tcl —— 强制重建被删掉的 gpu IP 生成目录
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2018/atk2018.xpr}
set LOG  [open "D:/ubuntu_iso/regen_gpu_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=== 强制重建 gpu IP ==="

open_project $PROJ
open_bd_design [get_files system.bd]
set BDOBJ [get_files system.bd]

# 强制: 先 reset 再 force 生成
L ">>> reset_target all"
catch {reset_target all $BDOBJ}
L ">>> generate_target all -force"
if {[catch {generate_target all $BDOBJ -force} e1]} { L " ⚠️ $e1" }
L ">>> 再次 generate_target all"
catch {generate_target all $BDOBJ}

if {[catch {validate_bd_design} e2]} { L " ❌ 校验失败: $e2"; close $LOG; exit 1 }
save_bd_design
L " ✅ BD 校验+保存"

# 检查 gpu IP 目录回来没有
set ipdir {D:/ubuntu_iso/atk2018/atk2018.srcs/sources_1/bd/system/ip}
set n 0
foreach d [glob -nocomplain $ipdir/system_gpu_0_0*] {
    set c [llength [glob -nocomplain $d/*]]
    L "  [file tail $d] : $c 项"
    incr n
}
L " gpu IP 目录数: $n"

# 检查工程是否认得
L " 源文件数 = [llength [get_files -of_objects [get_filesets sources_1]]]"
close $LOG
exit 0
