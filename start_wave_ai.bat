@echo off
REM ============================================================
REM  start_wave_ai.bat - start waveform multimodal AI service (port 8000)
REM
REM  FIX HISTORY (2026-10-29 10:58)
REM    Four bugs fixed:
REM    1) Chinese comments broke cmd parsing (file was UTF-8, cmd reads GBK)
REM       => garbage executed as commands => exit 255
REM       FIX: this file is ASCII-only.
REM    2) `python` not found in Startup environment PATH
REM       FIX: use %LOCALAPPDATA% (expanded at runtime, never written in file).
REM          NOTE: the Windows username is Chinese, so a hardcoded
REM          C:\Users\<chinese>\... path would put non-ASCII bytes back
REM          into this file and break it again.
REM    3) Chinese directory names in SRC/DELIV broke cmd
REM       FIX: English junctions ai_src / ai_deliv -> the real folders.
REM    4) Missing existence checks
REM
REM  Purpose: provide cloud AI analysis for the FPGA board (vision_v2)
REM ============================================================

set PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
set SRC=D:\ubuntu_iso\ai_src
set DELIV=D:\ubuntu_iso\ai_deliv
set LOG=D:\ubuntu_iso\_ai_service.log
set ERR=D:\ubuntu_iso\_ai_service.err

cd /d "%SRC%"

REM Skip if port 8000 already listening
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 0

if not exist "%PY%" exit /b 2
if not exist "%DELIV%\model_bundle.pt" exit /b 3

start "" /b "%PY%" -m wave_ai.serve --model "%DELIV%\model_bundle.pt" --anomaly "%DELIV%\anomaly_stats.npz" --host 0.0.0.0 --port 8000 >> "%LOG%" 2>> "%ERR%"
exit /b 0
