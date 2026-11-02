# generate_hdf_cnn3.tcl —— cnn3 工程 .sysdef + 复制为 .hdf
set proj "D:/FPGA2026_PRJ/zynq_ai_accel"
open_project "$proj/build/vivado_prj_cnn3/chain_prj.xpr"
set hwdef  "$proj/build/vivado_prj_cnn3/chain_prj.runs/impl_1/design_1_wrapper.hwdef"
set bit    "$proj/board/chain_cnn3.bit"
set sysdef "$proj/board/chain_cnn3.sysdef"
puts "HWDF: [file exists $hwdef]  BIT: [file exists $bit]"
write_sysdef -hwdef $hwdef -bitfile $bit -file $sysdef -force
file copy -force $sysdef "$proj/board/chain_cnn3.hdf"
puts "HDF copied size [file size $proj/board/chain_cnn3.hdf]"
exit
