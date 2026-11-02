# test2026.tcl —— 测试 Vivado 2026.1 是否可用 + 是否支持 xc7z020
puts "=========================================="
puts " Vivado 版本: [version -short]"
puts " 完整版本:   [version]"
puts "=========================================="
if {[catch {
    create_project -in_memory -part xc7z020clg400-2
    puts "✅ 器件 xc7z020clg400-2 可用 (Zynq-7020)"
    puts "   当前工程器件: [get_property PART [current_project]]"
} e]} {
    puts "❌ 创建工程失败: $e"
}
puts "=========================================="
puts " 已安装的器件家族:"
foreach fam [lsort [get_parts -quiet]] {
    # 只打印部分
}
set fams {}
foreach p [get_parts -quiet *7z020*] { lappend fams $p }
puts "  含 7z020 的器件: [llength $fams]"
foreach p [lrange $fams 0 5] { puts "    $p" }
puts "=========================================="
puts " 许可状态:"
if {[catch {
    set lic [get_licenses -quiet]
    puts "   许可证数: [llength $lic]"
} e2]} {
    puts "   (查不到, 可能不需要许可证)"
}
puts "TEST-DONE"
exit 0
