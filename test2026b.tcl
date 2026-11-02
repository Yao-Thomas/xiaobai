# test2026b.tcl —— ASCII only, verify part support
puts "=========================================="
puts " Vivado: [version -short]"
puts "=========================================="
if {[catch {
    create_project -in_memory -part xc7z020clg400-2
    puts "PART OK: xc7z020clg400-2  (Zynq-7020)"
    puts "  current part = [get_property PART [current_project]]"
} e]} {
    puts "PART FAILED: $e"
}
puts "=========================================="
set n 0
foreach p [get_parts -quiet *7z020*] { incr n }
puts "parts matching *7z020*: $n"
puts "=========================================="
puts "TEST-DONE"
exit 0
