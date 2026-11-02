puts "=== Synthesis flows ==="
foreach f [list_property_value FLOW [get_runs -quiet]] { }
create_project -force _tmpflow D:/ubuntu_iso/_tmpflow -part xc7z020clg400-2
puts "--- FLOW 可选值 ---"
catch {puts [list_property_value FLOW [current_project]]}
catch {puts [get_property FLOW [get_runs]]}
puts "--- 用 create_run -help 看用法 ---"
catch {create_run -help}
exit 0
