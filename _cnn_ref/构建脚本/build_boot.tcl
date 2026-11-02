# ============================================================================
# build_boot.tcl —— 2018.3 SDK(xsct) 无头流程：hw -> BSP -> app -> FSBL -> 产物
# 前置：run_bd_board + run_synth_board 已生成 design_1.hwh；write_sysdef 已生成 .hdf
# 说明：BSP 需要先 build 才会生成 xil_*.h 头文件，故先 build BSP 再 build app/fsbl。
# ============================================================================
set proj_root "D:/FPGA2026_PRJ/zynq_ai_accel"
set ws        "$proj_root/board/sdk_ws"
set hdf       "$proj_root/board/chain_board.hdf"
set app_src   "$proj_root/src/ps_sw"

setws $ws
puts "==== 1) createhw ===="
if {[catch { createhw -name chain_hw -hwspec $hdf } e]} { puts "FAIL createhw: $e"; exit 1 }
puts "==== 2) createbsp ===="
if {[catch { createbsp -name chain_bsp -hwproject chain_hw -proc ps7_cortexa9_0 -os standalone } e]} { puts "FAIL createbsp: $e"; exit 1 }
puts "==== 2.5) build BSP (chain_bsp) ===="
if {[catch { projects -build -name chain_bsp -type bsp } e]} { puts "FAIL build bsp: $e"; exit 1 }
puts "=== createapp (empty) ==="
if {[catch { createapp -name chain_app -hwproject chain_hw -bsp chain_bsp -proc ps7_cortexa9_0 -app {Empty Application} -lang c } e]} { puts "FAIL createapp: $e"; exit 1 }
puts "=== import main.c ==="
if {[catch { importsources -name chain_app -path $app_src } e]} { puts "FAIL importsources: $e"; exit 1 }
puts "=== build app ==="
if {[catch { projects -build -name chain_app -type app } e]} { puts "FAIL build app: $e"; exit 1 }
puts "=== create FSBL ==="
if {[catch { createapp -name fsbl -hwproject chain_hw -proc ps7_cortexa9_0 -app {Zynq FSBL} } e]} { puts "FAIL create fsbl: $e"; exit 1 }
puts "=== build FSBL bsp (fsbl_bsp) ==="
if {[catch { projects -build -name fsbl_bsp -type bsp } e]} { puts "FAIL build fsbl_bsp: $e"; exit 1 }
puts "=== build FSBL ==="
if {[catch { projects -build -name fsbl -type app } e]} { puts "FAIL build fsbl: $e"; exit 1 }
puts "==== DONE ===="
exit 0
