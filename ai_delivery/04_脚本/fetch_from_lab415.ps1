# fetch_from_lab415.ps1 -- pull deliverables + reports back from Lab415.
# ASCII only (Windows PowerShell 5.1 reads .ps1 as ANSI).

param(
    [string]$Remote = "lab415",
    [string]$RemoteRoot = "/data/pengyc_fzu/fpga2026_ai",
    [string]$LocalRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $LocalRoot) {
    $LocalRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$SSHOPTS = @('-o','BatchMode=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=NUL')

$dst = Join-Path $LocalRoot "deliverables"
New-Item -ItemType Directory -Force $dst | Out-Null

Write-Host "pulling deliverables -> $dst"
& scp @SSHOPTS -r "${Remote}:${RemoteRoot}/deliverables/." $dst
if ($LASTEXITCODE -ne 0) { throw "scp deliverables failed" }

# reports (small json/md only)
$repDst = Join-Path $LocalRoot "runs"
New-Item -ItemType Directory -Force $repDst | Out-Null
foreach ($r in @("wavenet_v3", "wavenet_v3_stft")) {
    New-Item -ItemType Directory -Force (Join-Path $repDst $r) | Out-Null
    foreach ($f in @("train_report.json", "ckpt_best.pt")) {
        & scp @SSHOPTS "${Remote}:${RemoteRoot}/runs/$r/$f" (Join-Path $repDst $r) 2>$null
    }
}
# env lock
& scp @SSHOPTS "${Remote}:${RemoteRoot}/requirements_lock.txt" $LocalRoot 2>$null

Write-Host "`n--- deliverables ---"
Get-ChildItem -Recurse $dst | Select-Object @{n='f';e={$_.FullName.Replace($dst,'')}}, Length |
    Format-Table -AutoSize
Write-Host "fetch done."
