# sync_to_lab415.ps1 -- push ai_training source tree to Lab415.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\sync_to_lab415.ps1
#   ... -WhatIf
#
# Implementation notes:
#   * Windows bsdtar crashes (0xC0000005) on this tree, and PowerShell 5.1
#     pipelines corrupt binary data -> use plain `scp -r` per directory.
#   * ASCII only: Windows PowerShell 5.1 reads .ps1 as ANSI.

param(
    [switch]$WhatIf,
    [string]$Remote = "lab415",
    [string]$RemoteRoot = "/data/pengyc_fzu/fpga2026_ai"
)

$ErrorActionPreference = "Stop"
$LocalRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SSHOPTS = @('-o','BatchMode=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=NUL')

Write-Host "local : $LocalRoot"
Write-Host "remote: ${Remote}:${RemoteRoot}"

$dirs = @()
foreach ($d in @('src','scripts','docs','tests','corpus')) {
    if (Test-Path (Join-Path $LocalRoot $d)) { $dirs += $d }
}
$files = @()
if (Test-Path (Join-Path $LocalRoot 'README.md')) { $files += 'README.md' }
if ($dirs.Count -eq 0 -and $files.Count -eq 0) { throw "nothing to sync" }

if ($WhatIf) {
    Write-Host "WhatIf: scp -r $($dirs -join ' ') $($files -join ' ') ${Remote}:${RemoteRoot}/"
    exit 0
}

& ssh @SSHOPTS $Remote "mkdir -p $RemoteRoot"
if ($LASTEXITCODE -ne 0) { throw "ssh mkdir failed" }

Push-Location $LocalRoot
try {
    foreach ($d in $dirs) {
        Write-Host "-> $d"
        & scp @SSHOPTS -r $d "${Remote}:${RemoteRoot}/"
        if ($LASTEXITCODE -ne 0) { throw "scp failed for $d" }
    }
    foreach ($f in $files) {
        Write-Host "-> $f"
        & scp @SSHOPTS $f "${Remote}:${RemoteRoot}/"
        if ($LASTEXITCODE -ne 0) { throw "scp failed for $f" }
    }
} finally { Pop-Location }

$remoteCmd = "cd $RemoteRoot && " +
             "find . -name '*.sh' -exec sed -i 's/\r`$//' {} + ; " +
             "find . -name '*.py' -exec sed -i 's/\r`$//' {} + ; " +
             "echo SYNC_OK && ls"
& ssh @SSHOPTS $Remote $remoteCmd
Write-Host "sync done."
