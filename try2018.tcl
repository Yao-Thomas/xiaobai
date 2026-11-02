#=====================================================================
#  try2018.tcl —— 测试 Vivado 2018.3 能否打开 2020.2 的工程
#  在【副本】上测试, 不动原工程
#=====================================================================
set PROJ $env(TEST_XPR)

puts "======================================================"
puts " 用 [version -short] 打开:"
puts "  $PROJ"
puts "======================================================"

if {[catch {open_project $PROJ} err]} {
    puts ""
    puts ">>> ❌ 打开失败:"
    puts "    $err"
    exit 1
}

puts ""
puts ">>> ✅ 工程打开了!"
puts "    工具版本: [version -short]"
if {[catch {set pt [get_property part [current_project]]} e2]} {
    puts "    器件: (读不到)"
} else {
    puts "    器件: $pt"
}

set bds [get_files -quiet *.bd]
puts "    BD 数量: [llength $bds]"
foreach b $bds { puts "      - $b" }

if {[llength $bds] > 0} {
    if {[catch {open_bd_design [lindex $bds 0]} e3]} {
        puts ""
        puts ">>> ❌ BD 打开失败: $e3"
        exit 2
    }
    puts ""
    puts ">>> ✅ BD 也打开了!"
    set cells [get_bd_cells]
    puts "    BD 实例数: [llength $cells]"
    foreach c [lrange $cells 0 15] {
        puts "      - [get_property NAME $c]"
    }
}

puts ""
puts ">>> 结论: 2018.3 【可以】处理这个工程 (可能带警告)"
exit 0
