setws D:/FPGA2026_PRJ/zynq_ai_accel/board/sdk_ws_cnn2
importsources -name chain_app -path D:/FPGA2026_PRJ/zynq_ai_accel/src/ps_sw_cnn2
projects -build -name chain_app -type app
puts "==== CNN2 APP REBUILD DONE ===="
exit
