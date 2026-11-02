# 启动多模态波形分析服务（Windows / PC 端）
#   用法：.\scripts\run_service.ps1            # 默认 0.0.0.0:8000
#         .\scripts\run_service.ps1 -Port 8765
#         .\scripts\run_service.ps1 -Model runs\v2_real\model_bundle.pt
param(
    [int]$Port = 8000,
    [string]$Model = "runs\v2_full\model_bundle.pt",
    [string]$Anomaly = "runs\v2_full\anomaly_stats.npz",
    [int]$Threads = 4
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

if (-not (Test-Path $Model)) {
    Write-Host "找不到模型：$Model" -ForegroundColor Red
    Write-Host "请先训练：python -m wave_ai.train --data data/ds_train --out runs/v2_full --epochs 16"
    exit 1
}

$argsList = @("-m", "wave_ai.serve", "--host", "0.0.0.0", "--port", "$Port",
              "--model", $Model, "--threads", "$Threads")
if (Test-Path $Anomaly) { $argsList += @("--anomaly", $Anomaly) }

Write-Host "启动服务：python $($argsList -join ' ')" -ForegroundColor Cyan
python @argsList
