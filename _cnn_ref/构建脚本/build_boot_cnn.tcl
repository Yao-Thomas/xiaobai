# build_boot_cnn.tcl —— M4b-1：SDK 无头构建 BSP + 应用(cnn) + FSBL
set proj_root "D:/FPGA2026_PRJ/zynq_ai_accel"
set ws        "$proj_root/board/sdk_ws_cnn"
set hdf       "$proj_root/board/chain_cnn.hdf"
set app_src   "$proj_root/src/ps_sw_cnn"

setws $ws
if {[catch { createhw -name chain_hw -hwspec $hdf } e]} { puts "FAIL createhw: $e"; exit 1 }
if {[catch { createbsp -name chain_bsp -hwproject chain_hw -proc ps7_cortexa9_0 -os standalone } e]} { puts "FAIL createbsp: $e"; exit 1 }
if {[catch { projects -build -name chain_bsp -type bsp } e]} { puts "FAIL build bsp: $e"; exit 1 }
if {[catch { createapp -name chain_app -hwproject chain_hw -bsp chain_bsp -proc ps7_cortexa9_0 -app {Empty Application} -lang c } e]} { puts "FAIL createapp: $e"; exit 1 }
if {[catch { importsources -name chain_app -path $app_src } e]} { puts "FAIL importsources: $e"; exit 1 }
if {[catch { projects -build -name chain_app -type app } e]} { puts "FAIL build app: $e"; exit 1 }
if {[catch { createapp -name fsbl -hwproject chain_hw -proc ps7_cortexa9_0 -app {Zynq FSBL} } e]} { puts "FAIL create fsbl: $e"; exit 1 }
if {[catch { projects -build -name fsbl_bsp -type bsp } e]} { puts "FAIL build fsbl_bsp: $e"; exit 1 }
if {[catch { projects -build -name fsbl -type app } e]} { puts "FAIL build fsbl: $e"; exit 1 }
puts "==== SDK CNN BUILD DONE ===="
exit 0
