# generate_hdf.tcl —— 用 write_sysdef 生成规范的 .sysdef（可复制为 .hdf）
set proj  "D:/FPGA2026_PRJ/zynq_ai_accel"
open_project "$proj/build/vivado_prj_board/chain_prj.xpr"
set hwdef  "$proj/build/vivado_prj_board/chain_prj.runs/impl_1/design_1_wrapper.hwdef"
set bit    "$proj/board/chain_board.bit"
set sysdef "$proj/board/chain.sysdef"
puts "HWDF exists: [file exists $hwdef]"
puts "BIT  exists: [file exists $bit]"
write_sysdef -hwdef $hwdef -bitfile $bit -file $sysdef
puts "SYSDEF done: [file exists $sysdef] (size [file size $sysdef])"
exit
