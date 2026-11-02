@echo off
call D:\Xilinx\2026.1\Vitis\settings64.bat >nul 2>&1
cd /d %~dp0

echo ########## 1/2  conv_pool  ##########
call v++ -c --mode hls --config "%CD%\conv_pool.cfg" --work_dir "%CD%\work\conv_pool" 2>&1
echo #### conv_pool EXIT: %ERRORLEVEL% ####

echo ########## 2/2  fc  ##########
call v++ -c --mode hls --config "%CD%\fc.cfg" --work_dir "%CD%\work\fc" 2>&1
echo #### fc EXIT: %ERRORLEVEL% ####

echo ########## ALL DONE ##########