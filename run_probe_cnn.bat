@echo off
call D:\Xilinx\2026.1\Vivado\settings64.bat >nul 2>&1
cd /d D:\ubuntu_iso
call vivado -mode batch -source probe_cnn_ip.tcl -log probe_cnn_ip.log -journal probe_cnn_ip.jou