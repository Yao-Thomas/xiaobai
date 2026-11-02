@echo off
chcp 65001 >nul
REM ════════════════════════════════════════════════════════════════
REM  start_fpga_daemon.bat —— 启动 FPGA 构建守护（PC 侧）
REM ════════════════════════════════════════════════════════════════
REM  为什么需要它：
REM    板载 agent 只会把构建任务【写进文件队列】
REM    （/home/zynq/fpga_jobs/<id>.request.json）
REM    真正跑 Vivado 的是这个守护进程（板子上跑不动 Vivado）。
REM    ★ 演示时忘了开它，agent 提交的任务就会一直躺在那里没人接。
REM
REM  用法：
REM    双击本文件即可（会开一个窗口，关掉窗口就停）
REM    开机自启：把快捷方式放到  shell:startup  目录
REM ════════════════════════════════════════════════════════════════

cd /d D:\ubuntu_iso

echo ══════════════════════════════════════════════════════
echo  系统管家小白 —— FPGA 构建守护（PC 侧）
echo ══════════════════════════════════════════════════════
echo  工作目录: %CD%
echo  板子:     192.168.110.144
echo  Vivado:   D:\Xilinx\2026.1\Vivado\bin\vivado.bat
echo.
echo  板载 agent 提交的任务会自动被这里取走执行。
echo  按 Ctrl+C 或关闭窗口停止。
echo ══════════════════════════════════════════════════════
echo.

python fpga_build_daemon.py --interval 10

echo.
echo [守护进程已退出] 按任意键关闭...
pause >nul
