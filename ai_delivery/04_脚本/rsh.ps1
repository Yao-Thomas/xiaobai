# rsh.ps1 -- run a local .sh file on Lab415 through ssh stdin.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\rsh.ps1 -Script scripts\_probe.sh
#
# Notes:
#   * Local .sh must use LF line endings (files written by the write tool are LF).
#   * The script is piped to the remote `bash -s`, so no chmod / scp is needed.
#   * All remote work happens under /data/pengyc_fzu/fpga2026_ai (root fs is full).
#   * ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI.

param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$Remote = "lab415",
    [int]$Timeout = 1800
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Script)) { throw "script not found: $Script" }

$text = [System.IO.File]::ReadAllText((Resolve-Path $Script))
$text = $text -replace "`r`n", "`n"
$text = $text -replace "`r", "`n"
if (-not $text.EndsWith("`n")) { $text += "`n" }

$SSHOPTS = @(
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=20',
    '-o', 'ServerAliveInterval=30',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=NUL'
)

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "ssh"
# Windows PowerShell 5.1 (.NET Framework) has no ArgumentList, so build Arguments.
$argList = @()
$argList += $SSHOPTS
$argList += $Remote
$psi.Arguments = ($argList -join ' ') + ' "bash -s"'
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false

$proc = [System.Diagnostics.Process]::Start($psi)
$proc.StandardInput.Write($text)
$proc.StandardInput.Close()

$outTask = $proc.StandardOutput.ReadToEndAsync()
$errTask = $proc.StandardError.ReadToEndAsync()
if (-not $proc.WaitForExit($Timeout * 1000)) {
    try { $proc.Kill() } catch {}
    Write-Output "[rsh] TIMEOUT after ${Timeout}s"
    exit 124
}
$out = $outTask.Result
$err = $errTask.Result

$errLines = ($err -split "`n") | Where-Object { $_ -notmatch 'Permanently added|known_hosts' }
Write-Output $out
$errClean = ($errLines -join "`n").Trim()
if ($errClean) { Write-Output "----- stderr -----"; Write-Output $errClean }
Write-Output "[rsh] exit=$($proc.ExitCode)"
