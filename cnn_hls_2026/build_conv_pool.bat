@echo off
call D:\Xilinx\2026.1\Vitis\settings64.bat >nul 2>&1
cd /d %~dp0
echo === ENV OK ===
where v++ 2>nul
echo === START HLS conv_pool ===
v++ -c --mode hls --config "%CD%\conv_pool.cfg" --work_dir "%CD%\work\conv_pool" 2>&1
echo === EXIT CODE: %ERRORLEVEL% ===