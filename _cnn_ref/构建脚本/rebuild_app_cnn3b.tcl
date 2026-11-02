setws D:/FPGA2026_PRJ/zynq_ai_accel/board/sdk_ws_cnn3b
importsources -name chain_app -path D:/FPGA2026_PRJ/zynq_ai_accel/src/ps_sw_cnn3b
projects -build -name chain_app -type app
puts "==== CNN3B APP REBUILD DONE ===="
exit
