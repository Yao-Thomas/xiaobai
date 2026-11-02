@echo off
REM build_agent_change.bat —— 出流（agent 直接改过 ipshared 的版本）
REM 用法: 双击，或 cmd /c "cd /d D:\ubuntu_iso && call build_agent_change.bat"
call D:\Xilinx\2026.1\Vivado\settings64.bat >nul 2>&1
cd /d D:\ubuntu_iso
call vivado -mode batch -source build_agent_change.tcl -log build_agent_change.log -journal build_agent_change.jou
