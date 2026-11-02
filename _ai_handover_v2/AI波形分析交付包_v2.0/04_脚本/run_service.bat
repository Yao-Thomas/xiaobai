@echo off
REM 启动多模态波形分析服务（Windows 双击即可，绕开 PowerShell 执行策略）
REM   可选参数：端口，例如 run_service.bat 8765
setlocal
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PORT=%1
if "%PORT%"=="" set PORT=8000
if not exist "runs\v2_full\model_bundle.pt" (
  echo 找不到模型 runs\v2_full\model_bundle.pt
  echo 请先训练：python -m wave_ai.train --data data/ds_train --out runs/v2_full --epochs 16
  pause
  exit /b 1
)
echo 启动服务：http://0.0.0.0:%PORT%
python -m wave_ai.serve --host 0.0.0.0 --port %PORT% ^
  --model runs\v2_full\model_bundle.pt ^
  --anomaly runs\v2_full\anomaly_stats.npz --threads 4
pause
