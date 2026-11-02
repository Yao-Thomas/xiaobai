# check_project.tcl —— 用守护跑一个真实的 Vivado 任务
#
# 目的：验证 fpga_build_daemon.py 能真的驱动 Vivado
#
# 内容：打开现有的 Navigator 工程 -> 报告资源占用 -> 写产物文件
#      （只读操作，不改工程，安全）

set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set OUT  {D:/ubuntu_iso/fpga_jobs/_vivado_report.txt}

puts "=== daemon 驱动 Vivado 测试 ==="
puts "时间: [clock format [clock seconds]]"

if {![file exists $PROJ]} {
    puts "!! 找不到工程 $PROJ"
    exit 1
}

open_project $PROJ
puts "PROJECT_OPENED"

set runs [get_runs -quiet]
puts "runs: $runs"

# 当前 bitstream 的信息
set bit {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.runs/impl_1/system_wrapper.bit}
if {[file exists $bit]} {
    set sz [file size $bit]
    puts "BITSTREAM: $bit"
    puts "BITSTREAM_SIZE: $sz"
}

# 写一个产物文件，让 daemon 能收集到
set f [open $OUT w]
puts $f "daemon 驱动 Vivado 测试"
puts $f "时间: [clock format [clock seconds]]"
puts $f "工程: $PROJ"
puts $f "runs: $runs"
if {[file exists $bit]} {
    puts $f "bitstream 大小: [file size $bit]"
    puts $f "bitstream mtime: [clock format [file mtime $bit]]"
}
close $f

puts "报告写到 $OUT"
puts "RESULT=OK"
exit 0
