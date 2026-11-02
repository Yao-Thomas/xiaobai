setws D:/FPGA2026_PRJ/zynq_ai_accel/board/sdk_ws_conv2d
importsources -name chain_app -path D:/FPGA2026_PRJ/zynq_ai_accel/src/ps_sw_conv2d
projects -build -name chain_app -type app
puts "==== APP REBUILD DONE ===="
exit
