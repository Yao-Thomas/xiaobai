#=====================================================================
#  import2018.tcl —— 用 Vivado 2018.3 新建工程, 只导入 BD + 约束
#  避开 2020.2 .xpr 里的各种 2020 专有配置
#=====================================================================
set SRC {D:/ubuntu_iso/tmp_try2018/Navigator_7020}
set NEW {D:/ubuntu_iso/tmp_try2018/atk2018}

puts "======================================================"
puts " 用 [version -short] 导入正点原子 BD"
puts "======================================================"

if {[file exists $NEW]} { file delete -force $NEW }
create_project -force atk2018 $NEW -part xc7z020clg400-2
puts " ✅ 新工程已建"

# ---- IP 仓库 ----
set repos {}
foreach d [glob -nocomplain $SRC/ip_repo/*] {
    if {[file isdirectory $d]} { lappend repos $d }
}
# 正点原子的 IP 可能也在工程自己的 ip_repo 下
foreach d [glob -nocomplain $SRC/Navigator_7020.srcs/sources_1/ip/*] {
    if {[file isdirectory $d]} { lappend repos $d }
}
puts " IP 仓库候选: [llength $repos] 个"
if {[llength $repos] > 0} {
    set_property ip_repo_paths $repos [current_project]
    update_ip_catalog -rebuild
    puts " ✅ IP 目录已更新"
}

# ---- BD ----
set bdfile $SRC/Navigator_7020.srcs/sources_1/bd/system/system.bd
if {![file exists $bdfile]} { error "找不到 BD: $bdfile" }
add_files -norecurse $bdfile
puts " ✅ BD 已加入"

# ---- 约束 ----
set xdcs [glob -nocomplain $SRC/Navigator_7020.srcs/constrs_1/**/*.xdc]
set xdcs2 [glob -nocomplain $SRC/Navigator_7020.srcs/constrs_1/*.xdc]
set allx [concat $xdcs $xdcs2]
puts " 找到约束文件: [llength $allx] 个"
foreach x $allx { puts "   - [file tail $x]" }
if {[llength $allx] > 0} {
    add_files -fileset constrs_1 -norecurse $allx
}

update_compile_order -fileset sources_1

# ---- 打开 BD ----
puts ""
puts ">>> 尝试打开 BD ..."
set RES [open "D:/ubuntu_iso/import2018_result.txt" w]
if {[catch {open_bd_design [get_files system.bd]} err]} {
    puts $RES "RESULT=FAIL"
    puts $RES "ERR=$err"
    close $RES
    puts ">>> ❌ BD 打开失败 (详情见 import2018_result.txt)"
    exit 2
}
puts ">>> ✅ BD 打开成功!"
set cells [get_bd_cells]
puts $RES "RESULT=OK"
puts $RES "CELLCOUNT=[llength $cells]"
foreach c [lsort [get_property NAME [get_bd_cells]]] {
    puts $RES "CELL=[get_property NAME $c]|[get_property VLNV $c]"
}
close $RES
puts "    BD 实例数: [llength $cells]"
puts ">>> 结论: 2018.3 可以处理这个 BD ✅ (详情见 import2018_result.txt)"
exit 0
