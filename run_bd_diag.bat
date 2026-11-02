@echo off
call D:\Xilinx\2026.1\Vivado\settings64.bat >nul 2>&1
cd /d D:\ubuntu_iso
call vivado -mode batch -source bd_diag_cnn.tcl -log bd_diag_cnn.log -journal bd_diag_cnn.jou