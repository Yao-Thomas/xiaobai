# generate_hdf_conv2d.tcl —— 为 conv2d 工程生成 .hdf（write_sysdef）
set proj "D:/FPGA2026_PRJ/zynq_ai_accel"
open_project "$proj/build/vivado_prj_conv2d/chain_prj.xpr"
set hwdef  "$proj/build/vivado_prj_conv2d/chain_prj.runs/impl_1/design_1_wrapper.hwdef"
set bit    "$proj/board/chain_conv2d.bit"
set sysdef "$proj/board/chain_conv2d.sysdef"
puts "HWDF: [file exists $hwdef]  BIT: [file exists $bit]"
write_sysdef -hwdef $hwdef -bitfile $bit -file $sysdef -force
puts "SYSDEF: [file exists $sysdef] size [file size $sysdef]"
exit
