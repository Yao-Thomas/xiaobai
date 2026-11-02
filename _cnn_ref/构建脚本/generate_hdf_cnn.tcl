# generate_hdf_cnn.tcl —— 为 cnn 工程生成 .sysdef 并复制为 .hdf（SDK createhw 用）
set proj "D:/FPGA2026_PRJ/zynq_ai_accel"
open_project "$proj/build/vivado_prj_cnn/chain_prj.xpr"
set hwdef  "$proj/build/vivado_prj_cnn/chain_prj.runs/impl_1/design_1_wrapper.hwdef"
set bit    "$proj/board/chain_cnn.bit"
set sysdef "$proj/board/chain_cnn.sysdef"
puts "HWDF: [file exists $hwdef]  BIT: [file exists $bit]"
write_sysdef -hwdef $hwdef -bitfile $bit -file $sysdef -force
puts "SYSDEF: [file exists $sysdef] size [file size $sysdef]"
file copy -force $sysdef "$proj/board/chain_cnn.hdf"
puts "HDF copied, size [file size $proj/board/chain_cnn.hdf]"
exit
