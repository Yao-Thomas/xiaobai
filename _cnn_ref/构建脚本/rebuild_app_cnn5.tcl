setws D:/FPGA2026_PRJ/zynq_ai_accel/board/sdk_ws_m4b5
importsources -name chain_app -path D:/FPGA2026_PRJ/zynq_ai_accel/src/ps_sw_m4b5
projects -build -name chain_app -type app
puts "==== CNN5 APP REBUILD DONE ===="
exit
