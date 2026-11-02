@echo off
call D:\Xilinx\2026.1\Vitis\settings64.bat >nul 2>&1
cd /d %~dp0
echo ########## fc  ##########
call v++ -c --mode hls --config "%CD%\fc.cfg" --work_dir "%CD%\work\fc" 2>&1
echo #### fc EXIT: %ERRORLEVEL% ####