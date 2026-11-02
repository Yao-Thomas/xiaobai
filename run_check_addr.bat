@echo off
call D:\Xilinx\2026.1\Vivado\settings64.bat >nul 2>&1
cd /d D:\ubuntu_iso
call vivado -mode batch -source check_cnn_addr.tcl -log check_cnn_addr.log -journal check_cnn_addr.jou